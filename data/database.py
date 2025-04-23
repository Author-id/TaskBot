from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase

# асинхронный движок
engine = create_async_engine("sqlite+aiosqlite:///TaskBot.db", echo=True)
# Создание фабрики асинхронных сессий
new_session = async_sessionmaker(engine, expire_on_commit=False)

# асинхронный генератор для получения сессии
async def get_session():
    async with new_session() as session:
        yield session


class Base(DeclarativeBase): pass


async def setup_database(): # настройка баз данных
    engine.echo = False
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all) # удаляем существующие таблицы
        await conn.run_sync(Base.metadata.create_all) # создаем таблицы заново
    engine.echo = True