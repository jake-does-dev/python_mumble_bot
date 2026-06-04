import logging

import python_mumble_bot.bot.client as client

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)

client.connect()
