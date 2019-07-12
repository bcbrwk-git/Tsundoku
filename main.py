import asyncio
import importlib

import aiohttp
import asyncpg
from quart import Quart

from config import get_config_value
from deluge.main import DelugeClient
import exceptions
import feed_poller


app = Quart("Tsundoku")


@app.before_serving
async def setup_session():
    """
    Creates an aiohttp ClientSession on startup using Quart's event loop.
    """
    loop = asyncio.get_event_loop()

    jar = aiohttp.CookieJar(unsafe=True)

    app.session = aiohttp.ClientSession(loop=loop, cookie_jar=jar)
    app.deluge = DelugeClient(app.session)


@app.before_serving
async def setup_db():
    """
    Creates a database pool for PostgreSQL interaction.
    """
    host = get_config_value("PostgreSQL", "host")
    port = get_config_value("PostgreSQL", "port")
    user = get_config_value("PostgreSQL", "user")
    password = get_config_value("PostgreSQL", "password")
    database = get_config_value("PostgreSQL", "database")

    loop = asyncio.get_event_loop()

    app.db_pool = await asyncpg.create_pool(
        host=host,
        port=port,
        user=user,
        password=password,
        database=database,
        loop=loop
    )


@app.before_serving
async def load_parsers():
    """
    Load all of the custom RSS parsers into the app.
    """
    parsers = [f"parsers.{p}" for p in get_config_value("Tsundoku", "parsers")]
    app.rss_parsers = []

    for parser in parsers:
        spec = importlib.util.find_spec(parser)
        if spec is None:
            raise exceptions.ParserNotFound(parser)

        lib = importlib.util.module_from_spec(spec)
        
        try:
            spec.loader.exec_module(lib)
        except Exception as e:
            raise exceptions.ParserFailed(parser, e) from e

        try:
            setup = getattr(lib, "setup")
        except AttributeError:
            raise exceptions.ParserMissingSetup(parser)

        try:
            new_context = app.app_context()
            app.rss_parsers.append(setup(new_context.app))
        except Exception as e:
            raise exceptions.ParserFailed(parser, e) from e


@app.before_serving
async def setup_poller():
    async def bg_task():
        await feed_poller.feed_poller(app.app_context())

    asyncio.ensure_future(bg_task())


@app.route("/")
async def index():
    return "placeholder"


@app.after_serving
async def cleanup():
    """
    Closes the database pool and the
    aiohttp ClientSession on script closure.
    """
    await app.db_pool.close()
    await app.session.close()

host = get_config_value("Tsundoku", "host")
port = get_config_value("Tsundoku", "port")

app.run(host=host, port=port)