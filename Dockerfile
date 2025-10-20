FROM python:3.11-slim

WORKDIR /app

# Install uv - modern Python package manager
RUN pip install --no-cache-dir uv

# Copy dependency files
COPY pyproject.toml uv.lock ./

# Copy source code (needed for installation)
COPY src/ ./src/

# Install dependencies using uv
RUN uv pip install --system --no-cache . && \
    uv pip install --system --no-cache fastapi uvicorn[standard]

# Environment variables
ENV OBSIDIAN_API_KEY=""
ENV OBSIDIAN_HOST="host.docker.internal"
ENV OBSIDIAN_PORT=27124
ENV OBSIDIAN_PROTOCOL=https
ENV HTTP_PORT=3000

# Expose HTTP port
EXPOSE 3000

# Run the HTTP server instead of stdio server
CMD ["python", "-m", "mcp_obsidian.http_server"]