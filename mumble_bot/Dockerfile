FROM python:3.10
ENV LANG=C.UTF-8
ENV LC_ALL=C.UTF-8
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONFAULTHANDLER=1
ENV PYTHONUNBUFFERED=1
ENV PIPENV_VENV_IN_PROJECT=1
RUN apt-get update && apt-get install -y ffmpeg libopus0 sox && rm -rf /var/lib/apt/lists/*
RUN pip install pipenv
COPY mumble_bot/Pipfile mumble_bot/Pipfile.lock ./
RUN pipenv install --deploy --ignore-pipfile
ENV PATH="/.venv/bin:/usr/local/bin:/usr/bin:/bin"
COPY pmb_core/ /opt/pmb_core/
RUN pipenv run pip install /opt/pmb_core
WORKDIR /app
COPY mumble_bot/ ./
ENTRYPOINT ["python", "-m", "python_mumble_bot"]
CMD ["10"]
