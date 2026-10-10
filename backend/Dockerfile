FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends git curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*
ENV HOME=/opt/tw-home PATH=/opt/tw-home/.local/bin:$PATH
# Entire CLI + graph plugin, copied from the host install (scripts/vendor-entire.sh).
COPY vendor/bin/ $HOME/.local/bin/
COPY vendor/share/ $HOME/.local/share/
RUN ln -sf $HOME/.local/share/entire/plugins/pkg/graph/entire-graph \
      $HOME/.local/share/entire/plugins/bin/entire-graph \
    && entire graph version && chmod -R a+rwX $HOME
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt
COPY tracewise /app/tracewise
WORKDIR /app
RUN git config --system --add safe.directory '*'
