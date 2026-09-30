#!/usr/bin/env python3
"""Synthetic Prometheus exporter for a small Kubernetes cluster - the
container layer underneath the existing shop.pyur.com services (see
webshop-metrics-exporter.py's SERVICES). Not a real integration - no
actual Kubernetes API server behind this - but the same 4 services
(frontend/checkout/catalog/search) now shown as Deployments with
multiple pod replicas across 3 worker nodes, so "Container-Monitoring"
has a concrete, already-familiar app to attach to instead of an
unrelated invented one.

Metric names follow real kube-state-metrics/cAdvisor conventions where
that's how the real exporters would name them (kube_pod_info,
kube_pod_status_phase, kube_pod_container_status_restarts_total,
kube_deployment_status_replicas_available/kube_deployment_spec_replicas)
- these ARE gauges/counters in the real exporters too. container_cpu_/
_memory_usage_percent and kube_node_cpu_/_memory_usage_percent are
simplified gauges (real cAdvisor/node_exporter expose cumulative
counters requiring rate()) - same simplification this repo's other
exporters already use for CPU/RAM (see docuware-metrics-exporter.py).

Baseline: 3 Ready nodes, 10 Running pods (frontend x3, checkout x3,
catalog x2, search x2), busy-but-healthy CPU/memory, no restarts.

State toggle: reads STATE_FILE (default /tmp/container-platform-state)
on every request. Missing or containing "healthy" -> normal values.
Containing "crashloop" -> one checkout pod (DEGRADED_POD) enters a
CrashLoopBackOff: restarts_total climbs, the pod goes not-Ready, its
deployment's available replicas drop below the desired count - so
break-container-platform.sh / fix-container-platform.sh can flip the
whole dashboard live without restarting this process, same pattern as
every other break-/fix- scenario in this demo.
"""
import http.server
import math
import os
import random
import time

PORT = int(os.environ.get("METRICS_PORT", "9600"))
STATE_FILE = os.environ.get("STATE_FILE", "/tmp/container-platform-state")

START = time.time()

NAMESPACE = "webshop"
NODES = ["node-1", "node-2", "node-3"]
# deployment -> (replica names, node each pod is scheduled on)
DEPLOYMENTS = {
    "frontend": ["frontend-1", "frontend-2", "frontend-3"],
    "checkout": ["checkout-1", "checkout-2", "checkout-3"],
    "catalog": ["catalog-1", "catalog-2"],
    "search": ["search-1", "search-2"],
}
POD_NODE = {}
_nodes_cycle = 0
for _deployment, _pods in DEPLOYMENTS.items():
    for _pod in _pods:
        POD_NODE[_pod] = NODES[_nodes_cycle % len(NODES)]
        _nodes_cycle += 1

POD_DEPLOYMENT = {pod: dep for dep, pods in DEPLOYMENTS.items() for pod in pods}
DEGRADED_POD = "checkout-2"  # the one break-container-platform.sh crash-loops

_restarts_total = dict.fromkeys(POD_DEPLOYMENT, 0)
_last_restart_tick = 0.0  # monotonic time.time() of the last simulated restart


def is_crashloop():
    try:
        with open(STATE_FILE) as fh:
            return fh.read().strip() == "crashloop"
    except FileNotFoundError:
        return False


def wave(period_s, low, high, phase=0.0):
    t = time.time() - START
    frac = (math.sin(2 * math.pi * (t / period_s) + phase) + 1) / 2
    jitter = random.uniform(-0.01, 0.01) * (high - low)
    return max(low, min(high, low + frac * (high - low) + jitter))


def render_metrics():
    global _last_restart_tick
    crashloop = is_crashloop()
    now = time.time()

    # A restart roughly every 25-40s while crash-looping - CrashLoopBackOff's
    # exponential backoff means it's not a tight loop, just persistent.
    if crashloop and now - _last_restart_tick > random.uniform(25, 40):
        _restarts_total[DEGRADED_POD] += 1
        _last_restart_tick = now

    lines = [
        "# HELP kube_node_info Static info row per Kubernetes worker node (value always 1).",
        "# TYPE kube_node_info gauge",
        "# HELP kube_node_status_ready Whether the node is in Ready condition (1=ready).",
        "# TYPE kube_node_status_ready gauge",
        "# HELP kube_node_cpu_usage_percent Node CPU utilization (simplified gauge - real node_exporter exposes cumulative counters).",
        "# TYPE kube_node_cpu_usage_percent gauge",
        "# HELP kube_node_memory_usage_percent Node memory utilization.",
        "# TYPE kube_node_memory_usage_percent gauge",
    ]
    for i, node in enumerate(NODES):
        lines.append(f'kube_node_info{{node="{node}"}} 1')
        lines.append(f'kube_node_status_ready{{node="{node}"}} 1')
        lines.append(f'kube_node_cpu_usage_percent{{node="{node}"}} {wave(70, 35, 65, phase=i * 2.1):.1f}')
        lines.append(f'kube_node_memory_usage_percent{{node="{node}"}} {wave(85, 45, 70, phase=i * 1.7):.1f}')

    lines += [
        "# HELP kube_pod_info Static info row per pod (value always 1).",
        "# TYPE kube_pod_info gauge",
        "# HELP kube_pod_status_phase Pod lifecycle phase (1=current phase, one series per pod+phase).",
        "# TYPE kube_pod_status_phase gauge",
        "# HELP kube_pod_container_status_ready Whether the pod's container passes its readiness probe (1=ready).",
        "# TYPE kube_pod_container_status_ready gauge",
        "# HELP kube_pod_container_status_restarts_total Container restart count.",
        "# TYPE kube_pod_container_status_restarts_total counter",
        "# HELP kube_pod_container_status_waiting_reason Reason a container isn't running (1=active), e.g. CrashLoopBackOff.",
        "# TYPE kube_pod_container_status_waiting_reason gauge",
        "# HELP container_cpu_usage_percent Container CPU utilization (simplified gauge - real cAdvisor exposes container_cpu_usage_seconds_total, a counter).",
        "# TYPE container_cpu_usage_percent gauge",
        "# HELP container_memory_usage_percent Container memory utilization.",
        "# TYPE container_memory_usage_percent gauge",
    ]
    for pod, deployment in POD_DEPLOYMENT.items():
        node = POD_NODE[pod]
        degraded_here = crashloop and pod == DEGRADED_POD
        lines.append(f'kube_pod_info{{pod="{pod}",namespace="{NAMESPACE}",node="{node}",deployment="{deployment}"}} 1')
        lines.append(f'kube_pod_status_phase{{pod="{pod}",namespace="{NAMESPACE}",phase="Running"}} 1')
        lines.append(f'kube_pod_container_status_ready{{pod="{pod}",namespace="{NAMESPACE}",container="{deployment}"}} {0 if degraded_here else 1}')
        lines.append(f'kube_pod_container_status_restarts_total{{pod="{pod}",namespace="{NAMESPACE}",container="{deployment}"}} {_restarts_total[pod]}')
        lines.append(f'kube_pod_container_status_waiting_reason{{pod="{pod}",namespace="{NAMESPACE}",reason="CrashLoopBackOff"}} {1 if degraded_here else 0}')
        cpu = wave(15, 85, 99, phase=hash(pod) % 10) if degraded_here else wave(60, 20, 55, phase=hash(pod) % 10)
        mem = 5.0 if degraded_here else wave(80, 30, 65, phase=hash(pod + "m") % 10)
        lines.append(f'container_cpu_usage_percent{{pod="{pod}",namespace="{NAMESPACE}",container="{deployment}"}} {cpu:.1f}')
        lines.append(f'container_memory_usage_percent{{pod="{pod}",namespace="{NAMESPACE}",container="{deployment}"}} {mem:.1f}')

    lines += [
        "# HELP kube_deployment_spec_replicas Desired replica count for a Deployment.",
        "# TYPE kube_deployment_spec_replicas gauge",
        "# HELP kube_deployment_status_replicas_available Available (Ready) replica count for a Deployment.",
        "# TYPE kube_deployment_status_replicas_available gauge",
    ]
    for deployment, pods in DEPLOYMENTS.items():
        desired = len(pods)
        not_ready = sum(1 for p in pods if crashloop and p == DEGRADED_POD)
        available = desired - not_ready
        lines.append(f'kube_deployment_spec_replicas{{deployment="{deployment}",namespace="{NAMESPACE}"}} {desired}')
        lines.append(f'kube_deployment_status_replicas_available{{deployment="{deployment}",namespace="{NAMESPACE}"}} {available}')

    return "\n".join(lines) + "\n"


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path != "/metrics":
            self.send_response(404)
            self.end_headers()
            return
        body = render_metrics().encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; version=0.0.4")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        pass


if __name__ == "__main__":
    http.server.HTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
