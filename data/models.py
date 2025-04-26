from sqlalchemy import Column, Integer, String, Date, DateTime, Boolean, ForeignKey
from sqlalchemy.orm import relationship
from datetime import datetime
from data.database import Base


class UserModel(Base): # модель пользователя
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    tg_id = Column(Integer, primary_key=True)
    username = Column(String(50), nullable=True)
    first_name = Column(String(50), nullable=False)
    last_name = Column(String(50), nullable=True)
    registration_date = Column(Date, default=datetime.utcnow)

    tasks = relationship(
        "TaskModel",
        back_populates="user",
        cascade="all, delete-orphan"
    ) # связь один ко многим


class TaskModel(Base): # модель задачи
    __tablename__ = "tasks"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False) # ссылка на пользователя
    title = Column(String(50), nullable=False)
    description = Column(String(150), nullable=True)
    due_date = Column(Date, nullable=True)
    is_done = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, onupdate=datetime.utcnow)

    user = relationship(
        "UserModel",
        back_populates="tasks") # связь многие к одному
