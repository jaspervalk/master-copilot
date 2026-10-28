from fastapi import APIRouter

from app.api.routes import (
    agenda,
    attention,
    chat,
    conversations,
    courses,
    documents,
    exam_prep,
    health,
    practice,
    query,
    stream,
    study,
    weeks,
)

api_router = APIRouter()
api_router.include_router(health.router, tags=["health"])
api_router.include_router(attention.router)
api_router.include_router(documents.router, tags=["documents"])
api_router.include_router(courses.router, tags=["courses"])
api_router.include_router(query.router, tags=["query"])
api_router.include_router(chat.router, tags=["chat"])
api_router.include_router(stream.router, tags=["chat"])
api_router.include_router(conversations.router, tags=["conversations"])
api_router.include_router(practice.router)
api_router.include_router(study.router)
api_router.include_router(exam_prep.router)
api_router.include_router(weeks.router)
api_router.include_router(agenda.router)
