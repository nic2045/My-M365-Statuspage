/**
 * Server-Sent Events (SSE) listener for live status updates.
 * Listens on /sse/status and updates the UI when incidents/services change.
 */

(function () {
  const RECONNECT_INTERVAL = 3000; // 3 seconds
  let eventSource = null;
  let reconnectAttempts = 0;
  const MAX_RECONNECT_ATTEMPTS = 10;

  function connect() {
    if (eventSource) {
      eventSource.close();
    }

    eventSource = new EventSource('/sse/status');

    eventSource.addEventListener('message', (event) => {
      try {
        const data = JSON.parse(event.data);
        handleStatusUpdate(data);
      } catch (e) {
        console.error('Failed to parse SSE data:', e);
      }
    });

    eventSource.addEventListener('error', () => {
      if (eventSource.readyState === EventSource.CLOSED) {
        attemptReconnect();
      }
    });

    reconnectAttempts = 0;
  }

  function attemptReconnect() {
    if (reconnectAttempts < MAX_RECONNECT_ATTEMPTS) {
      reconnectAttempts++;
      const delay = RECONNECT_INTERVAL * Math.pow(1.5, reconnectAttempts - 1);
      console.log(`SSE reconnecting in ${Math.round(delay)}ms (attempt ${reconnectAttempts})`);
      setTimeout(connect, delay);
    } else {
      console.warn('SSE connection failed after max retries');
    }
  }

  function handleStatusUpdate(data) {
    const { event_type, service, incident_id, title, status, timestamp } = data;

    switch (event_type) {
      case 'incident.created':
        showToast(`New incident: ${title}`, 'warning');
        // Refresh incidents list on status page
        if (window.location.pathname === '/') {
          refreshIncidentsList();
        }
        break;

      case 'incident.updated':
        showToast(`Updated: ${title}`, 'info');
        break;

      case 'incident.resolved':
        showToast(`Resolved: ${title}`, 'success');
        refreshIncidentsList();
        break;

      case 'service.status_changed':
        // Update service status indicator
        updateServiceStatus(service, status);
        showToast(`${service}: ${status}`, 'info');
        break;

      default:
        break;
    }
  }

  function showToast(message, level = 'info') {
    // Fire custom event for toast handler (if present)
    const event = new CustomEvent('show-toast', {
      detail: { message, level },
    });
    document.dispatchEvent(event);
  }

  function refreshIncidentsList() {
    // Re-fetch incident list via JavaScript (could also hard-reload page)
    const incidentsContainer = document.querySelector('[data-incidents-container]');
    if (!incidentsContainer) return;

    // Simple approach: reload the incidents section via AJAX
    fetch('/api/incidents')
      .then((r) => r.json())
      .then((incidents) => {
        // Update DOM with new incidents list
        // This is a stub — implement based on your template structure
        console.log('Incidents refreshed:', incidents);
      })
      .catch((e) => console.error('Failed to refresh incidents:', e));
  }

  function updateServiceStatus(serviceName, newStatus) {
    // Update service card/row in the services list
    const serviceRow = document.querySelector(`[data-service-name="${serviceName}"]`);
    if (!serviceRow) return;

    // Update status badge color based on newStatus
    const statusBadge = serviceRow.querySelector('[data-status-badge]');
    if (statusBadge) {
      statusBadge.setAttribute('data-status', newStatus);
      // Also update class for styling (depends on your CSS)
    }
  }

  // Start connection when DOM is ready
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', connect);
  } else {
    connect();
  }

  // Clean up on page unload
  window.addEventListener('beforeunload', () => {
    if (eventSource) {
      eventSource.close();
    }
  });
})();
