# Study Buddy: a Gemini chatbot that remembers you (Walrus Memory)

Study Buddy is a small Django chat app for university students. It uses
**Google Gemini** as the language model and **Walrus Memory** (`memwal` Python SDK)
to remember each student between conversations, sessions and devices.

- Each student gets their own Walrus Memory namespace (`studybuddy-<name>`).
- Every message a student sends is stored as a memory.
- Before every reply, the bot recalls the memories most relevant to the new
  message and gives them to Gemini.
- The page shows which memories were recalled, and lists everything remembered.
- `friction_log.txt` is written automatically with timings and any Walrus errors.

## Run it locally

1. Install Python 3.9 or newer.
2. `pip install -r requirements.txt`
3. Copy `.env.example` to `.env` and fill in:
   - `MEMWAL_PRIVATE_KEY` and `MEMWAL_ACCOUNT_ID` from https://staging.memory.walrus.xyz
   - `GEMINI_API_KEY` from https://aistudio.google.com
4. `python manage.py runserver`
5. Open http://127.0.0.1:8000, enter a name, and chat.
   Use the same name again later to get your memories back.

## Notes
- There is no database; the sign-in is just a name stored in a signed cookie.
  This is a demo, not real authentication.
- Never commit your `.env` file.
