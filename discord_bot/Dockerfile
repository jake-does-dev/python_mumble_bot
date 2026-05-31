FROM python:3.10
ENV LANG=C.UTF-8
ENV LC_ALL=C.UTF-8
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONFAULTHANDLER=1
ENV PYTHONUNBUFFERED=1
ENV PIPENV_VENV_IN_PROJECT=1
RUN apt-get update && apt-get install -y ffmpeg libopus0 && rm -rf /var/lib/apt/lists/*
RUN pip install pipenv
COPY discord_bot/Pipfile ./
RUN pipenv install --skip-lock
ENV PATH="/.venv/bin:/usr/local/bin:/usr/bin:/bin"
COPY pmb_core/ /opt/pmb_core/
RUN pipenv run pip install /opt/pmb_core
WORKDIR /app
COPY discord_bot/ ./
ENTRYPOINT ["python", "-m", "python_discord_bot"]
