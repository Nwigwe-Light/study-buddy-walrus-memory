"""Study Buddy: a Gemini chatbot that remembers each student using Walrus Memory.

Each student gets their own Walrus Memory namespace, so what Ada tells the bot
is never mixed with what Chidi tells it. Every message is stored as a memory,
and before every reply the bot recalls the memories most relevant to the new
message and gives them to Gemini.
"""
import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from memwal import MemWalSync, RecallParams

FRICTION_LOG = Path(__file__).resolve().parent.parent / "friction_log.txt"

SYSTEM_PROMPT = """You are Study Buddy, a friendly study partner for university students.
You remember students between conversations. Below is what you remember about
this student from earlier chats (it may be empty, and may be incomplete).

Rules:
- Use the remembered facts naturally when they are relevant: their courses,
  weak topics, exam dates, goals, how they like to learn.
- If a remembered fact is relevant, mention it briefly so the student can see
  you remembered (for example: "Last time you said calculus limits were tough...").
- Never invent memories. If you do not remember something, say so and ask.
- Keep replies short and practical: 2 to 5 sentences unless asked for more.
- Write plain text only. Never use LaTeX or dollar signs for math; write formulas like f = 1/T.
- Think silently. Do not show drafts, rules or notes. Output ONLY your final reply to the student, wrapped exactly like this: <reply>your reply here</reply>

What you remember about {name}:
{memories}
"""


def log_friction(note):
    """Print and append a timestamped line (used for the bug report)."""
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    line = f"[{stamp}] {note}"
    print(line, flush=True)
    try:
        with open(FRICTION_LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def make_slug(name):
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug[:30]


def get_memwal(slug):
    return MemWalSync.create(
        key=os.environ["MEMWAL_PRIVATE_KEY"],
        account_id=os.environ["MEMWAL_ACCOUNT_ID"],
        env=os.environ.get("MEMWAL_ENV", "staging"),
        namespace=f"studybuddy-{slug}",
    )


def recall_memories(slug, query, limit=6):
    """Return a list of remembered text lines relevant to `query`."""
    started = time.time()
    mem = get_memwal(slug)
    try:
        result = mem.recall(RecallParams(query=query))
        texts = [m.text for m in result.results][:limit]
        log_friction(
            f"recall ok user={slug} found={len(texts)} took={time.time() - started:.1f}s"
        )
        return texts
    finally:
        mem.close()


def store_memory(slug, text):
    """Save a memory. Returns quickly; Walrus finishes the upload in the background."""
    started = time.time()
    mem = get_memwal(slug)
    try:
        mem.remember(text)
        log_friction(
            f"remember accepted user={slug} took={time.time() - started:.1f}s"
        )
    finally:
        mem.close()


def ask_gemini(system_text, history, message):
    models = [
        m.strip()
        for m in os.environ.get("GEMINI_MODEL", "gemma-3-27b-it").split(",")
        if m.strip()
    ]
    contents = [
        {
            "role": "user" if m.get("role") == "user" else "model",
            "parts": [{"text": str(m.get("text", ""))}],
        }
        for m in history[-6:]
    ]
    last_status = None
    for model in models:
        if model.startswith("gemma"):
            # Gemma has no system-instruction field, so put the rules in the message.
            full = f"{system_text}\n\nStudent's new message:\n{message}"
            body = {"contents": contents + [{"role": "user", "parts": [{"text": full}]}]}
        else:
            body = {
                "system_instruction": {"parts": [{"text": system_text}]},
                "contents": contents + [{"role": "user", "parts": [{"text": message}]}],
            }
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
        resp = httpx.post(
            url,
            json=body,
            headers={"x-goog-api-key": os.environ["GEMINI_API_KEY"]},
            timeout=60,
        )
        if resp.status_code in (400, 404, 429, 500, 503):
            last_status = resp.status_code
            log_friction(f"gemini model={model} status={resp.status_code}, trying next model")
            continue
        resp.raise_for_status()
        data = resp.json()
        try:
            parts = data["candidates"][0]["content"]["parts"]
            text = "".join(p.get("text", "") for p in parts if not p.get("thought")).strip()
            if "<reply>" in text:
                text = text.split("<reply>")[-1].split("</reply>")[0].strip()
            elif '"' in text:
                quoted = re.findall(r'"([^"]{20,})"', text)
                if quoted:
                    text = quoted[-1].strip()
            return text or "Sorry, I couldn't put together a reply. Could you rephrase it?"
        except (KeyError, IndexError):
            log_friction(f"gemini odd response from {model}: {str(data)[:400]}")
            return "Sorry, I couldn't put together a reply to that. Could you rephrase it?"
    raise RuntimeError(f"All models failed (last status {last_status})")

def index(request):
    if request.session.get("name"):
        return redirect("chat")
    return render(request, "chat/index.html")


def chat_page(request):
    if request.method == "POST":
        name = request.POST.get("name", "").strip()[:30]
        slug = make_slug(name)
        if not slug:
            return render(request, "chat/index.html", {"error": "Enter a name using letters or numbers."})
        request.session["name"] = name
        request.session["slug"] = slug
        return redirect("chat")
    if not request.session.get("slug"):
        return redirect("index")
    return render(request, "chat/chat.html", {"name": request.session["name"]})


def logout_view(request):
    request.session.flush()
    return redirect("index")


@csrf_exempt
@require_POST
def chat_api(request):
    slug = request.session.get("slug")
    name = request.session.get("name")
    if not slug:
        return JsonResponse({"error": "Not signed in."}, status=401)

    payload = json.loads(request.body or "{}")
    message = str(payload.get("message", "")).strip()
    history = payload.get("history", [])
    if not message:
        return JsonResponse({"error": "Empty message."}, status=400)

    # 1. Recall what we already know about this student.
    recalled = []
    try:
        recalled = recall_memories(slug, message)
    except Exception as exc:  # keep chatting even if memory is down
        log_friction(f"RECALL ERROR user={slug}: {type(exc).__name__}: {exc}")

    memory_block = "\n".join(f"- {t}" for t in recalled) or "(nothing yet)"
    system_text = SYSTEM_PROMPT.format(name=name, memories=memory_block)

    # 2. Ask Gemini, with the recalled memories in the prompt.
    try:
        reply = ask_gemini(system_text, history, message)
    except Exception as exc:
        log_friction(f"GEMINI ERROR user={slug}: {type(exc).__name__}: {exc}")
        return JsonResponse({"error": "Gemini request failed. Check the server log."}, status=502)

    # 3. Save what the student just said, so next time the bot knows it.
    try:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        store_memory(slug, f"On {today}, {name} said: {message}")
    except Exception as exc:
        log_friction(f"REMEMBER ERROR user={slug}: {type(exc).__name__}: {exc}")

    return JsonResponse({"reply": reply, "recalled": recalled})


@csrf_exempt
def memories_api(request):
    """List what the bot currently remembers about the signed-in student."""
    slug = request.session.get("slug")
    if not slug:
        return JsonResponse({"error": "Not signed in."}, status=401)
    try:
        texts = recall_memories(slug, "everything we know about this student", limit=20)
    except Exception as exc:
        log_friction(f"MEMORIES LIST ERROR user={slug}: {type(exc).__name__}: {exc}")
        return JsonResponse({"memories": [], "error": str(exc)})
    return JsonResponse({"memories": texts})
