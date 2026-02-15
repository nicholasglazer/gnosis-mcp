FROM python:3.11-slim

WORKDIR /app

COPY pyproject.toml README.md LICENSE ./
COPY src/ src/

RUN pip install --no-cache-dir .

ENV GNOSIS_MCP_TRANSPORT=stdio

ENTRYPOINT ["gnosis-mcp"]
CMD ["serve"]
