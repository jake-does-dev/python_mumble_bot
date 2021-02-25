# Python Mumble Bot

## Setup
```sh
# Install dependencies
pipenv install --dev

# Setup pre-commit and pre-push hooks
pipenv run pre-commit install -t pre-commit
pipenv run pre-commit install -t pre-push

# Setup mongodb - see python_mumble_bot/db/mongo_db_setup.md for more

# Setup environment variables:
MONGODB_HOST # the ip address of the MongoDB server
MONGODB_USERNAME # the user authorised to access the voice_clips database on the MongoDB server
MONGODB_PASSWORD # associated password
MUMBLE_SERVER_HOST # the ip address of the Mumble server
MUMBLE_SERVER_USERNAME # the name of the bot
MUMBLE_SERVER_PASSWORD # the mumble server password
MUMBLE_SERVER_ROOT_CHANNEL # the root channel on the associated Mumble server
```

## Credits
This package was created with Cookiecutter and the [sourcery-ai/python-best-practices-cookiecutter](https://github.com/sourcery-ai/python-best-practices-cookiecutter) project template.
