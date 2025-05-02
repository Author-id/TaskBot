from sqlalchemy import Column, Integer, String, Date, DateTime, Boolean, ForeignKey
from sqlalchemy.orm import relationship
from datetime import datetime
from data.database import Base


class UserModel(Base): # модель пользователя
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    tg_id = Column(Integer, primary_key=True, nullable=False)
    username = Column(String(50), nullable=True)

    tasks = relationship(
        "TaskModel",
        back_populates="user",
        cascade="all, delete-orphan"
    ) # связь один ко многим


class TaskModel(Base): # модель задачи
    __tablename__ = "tasks"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.tg_id"), nullable=False) # ссылка на пользователя
    title = Column(String(50), nullable=False)
    tag_id = Column(Integer, ForeignKey("tags.id"), nullable=True)
    due_date = Column(Date, nullable=True)
    is_done = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    tag = relationship(
        "TagModel",
        back_populates="tasks"
    ) # связь многие к одному
    user = relationship(
        "UserModel",
        back_populates="tasks"
    ) # связь многие к одному


class TagModel(Base): # модель тега
    __tablename__ = "tags"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.tg_id"), nullable=False)
    title = Column(String(20), nullable=False, unique=True)

    tasks = relationship(
        "TaskModel",
        back_populates="tag"
    ) # связь один ко многим
