FROM python:3.12-slim

WORKDIR /app
ENV NODE_ENV=production
ENV PORT=8080
ENV HOST=0.0.0.0

COPY . .

EXPOSE 8080
CMD ["python", "simple-server.py"]
