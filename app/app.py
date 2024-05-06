# Copyright 2023 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
from flask import Flask, request
import logging
import os
import signal
import sys
import threading
import time

import opentelemetry
from opentelemetry import trace
#from opentelemetry.exporter import jaeger
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
    OTLPSpanExporter,
)
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
#from opentelemetry.sdk.trace.samplers import AlwaysOnSampler
from opentelemetry.semconv.resource import ResourceAttributes
from opentelemetry.trace import SpanKind

# Create channel to listen for signals.
signalChan = threading.Event()

# Set up logging.
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
handler = logging.StreamHandler(sys.stdout)
handler.setFormatter(logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s"))
logger.addHandler(handler)

# Set up trace exporter.
#jaeger_exporter = jaeger.JaegerExporter(
#    agent_host_name=os.environ.get("JAEGER_AGENT_HOST", "localhost"),
#    agent_port=os.environ.get("JAEGER_AGENT_PORT", 6831),
#)
#otlp_exporter = OTLPSpanExporter(endpoint=os.environ.get("OTLP_ENDPOINT", "localhost:4317"))

# Set up tracer provider.
resource = Resource(
    {
        ResourceAttributes.SERVICE_NAME: "example-app",
        ResourceAttributes.SERVICE_VERSION: "1.0.0",
    }
)
trace_provider = TracerProvider(
    resource=resource,
    #sampler=AlwaysOnSampler(),
    #span_processor=BatchSpanProcessor(otlp_exporter),
)
processor =  OTLPSpanExporter(endpoint=os.environ.get("OTLP_ENDPOINT", "localhost:4317"))
trace_provider.add_span_processor(processor)
opentelemetry.trace.set_tracer_provider(trace_provider)

# Set up metrics exporter.
# TODO: Implement metrics exporter.

# SIGINT handles Ctrl+C locally.
# SIGTERM handles Cloud Run termination signal.
signal.signal(signal.SIGINT, lambda signum, frame: signalChan.set())
signal.signal(signal.SIGTERM, lambda signum, frame: signalChan.set())

# Start HTTP server.
def handler(request):
    # Get trace context propagated from HTTP request.
    trace_header = request.headers.get("traceparent")
    if trace_header:
        trace_id, span_id = trace_header.split("-")
        ctx = opentelemetry.trace.set_span_in_context(
            request.environ.get("HTTP_X_CLOUD_TRACE_CONTEXT"),
            trace_id=trace_id,
            span_id=span_id,
        )
    else:
        ctx = opentelemetry.trace.set_span_in_context(request.environ.get("HTTP_X_CLOUD_TRACE_CONTEXT"))

    # Start a new span.
    with trace_provider.tracer("example-app").start_as_current_span(
        "foo", kind=SpanKind.SERVER
    ) as span:
        # Extract current span ID.
        span_id = span.get_span_context().span_id
        trace_id = span.get_span_context().trace_id

        # Open logging file.
        with open("/logging/sample-app.log", "a") as f:
            # Log incoming request with spanID.
            logger.info(f"Request: {request.method} {request.path}", extra={"trace_id": trace_id, "span_id": span_id})

        # Write traces.
        generate_spans(ctx, trace_provider.tracer("example-app"), logger, 10)

        # Update metric.
        # TODO: Implement metric update.

    return "Logged request to /logging/sample-app.log"


def generate_spans(ctx, tracer, logger, id):
    if id > 0:
        with tracer.start_as_current_span(f"foo-{id}", kind=SpanKind.INTERNAL) as span:
            logger.info(f"Generating span {id}...", extra={"trace_id": span.get_span_context().trace_id, "span_id": span.get_span_context().span_id})
            generate_spans(ctx, tracer, logger, id - 1)
    else:
        logger.info("Done.")


def main():
    # Start HTTP server.
    

    app = Flask(__name__)
    app.add_url_rule("/", "index", handler, methods=["GET"])

    # Start the server in a separate thread to avoid blocking the main thread.
    threading.Thread(target=app.run, kwargs={"host": "0.0.0.0", "port": 8080}).start()

    # Wait for the signal to terminate the server.
    signalChan.wait()

    # Gracefully shutdown the server.
    logger.info("Shutting down server...")
    app.shutdown()

    # Flush any remaining spans.
    trace_provider.force_flush()

    logger.info("Server exited.")


if __name__ == "__main__":
    main()
