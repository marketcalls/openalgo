FROM python:3.9

WORKDIR /app

ADD . /app

RUN pip install -r requirements.txt