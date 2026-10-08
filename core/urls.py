from django.urls import path

from chat import views

urlpatterns = [
    path("", views.index, name="index"),
    path("chat/", views.chat_page, name="chat"),
    path("api/chat/", views.chat_api, name="chat_api"),
    path("api/memories/", views.memories_api, name="memories_api"),
    path("logout/", views.logout_view, name="logout"),
]
