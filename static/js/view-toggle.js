/**
 * Service view toggle: Table ↔ Cards
 * Persists preference to localStorage as 'serviceViewMode'
 */

const STORAGE_KEY = 'serviceViewMode';
const DEFAULT_VIEW = 'table';
const VIEWS = {
  table: 'table',
  cards: 'cards',
};

function initViewToggle() {
  const container = document.querySelector('[data-services-container]');
  const toggleBtn = document.querySelector('[data-view-toggle-btn]');

  if (!container || !toggleBtn) return;

  let currentView = localStorage.getItem(STORAGE_KEY) || DEFAULT_VIEW;

  // Set initial state
  setView(currentView, container, toggleBtn);

  // Toggle on click
  toggleBtn.addEventListener('click', () => {
    currentView = currentView === VIEWS.table ? VIEWS.cards : VIEWS.table;
    localStorage.setItem(STORAGE_KEY, currentView);
    setView(currentView, container, toggleBtn);
  });
}

function setView(view, container, btn) {
  const services = container.querySelectorAll('[data-service-card]');

  if (view === VIEWS.cards) {
    // Switch to cards layout
    container.classList.remove('flex', 'flex-col');
    container.classList.add('grid', 'grid-cols-1', 'sm:grid-cols-2', 'lg:grid-cols-3', 'gap-4');

    // Hide table rows, show cards
    services.forEach((svc) => {
      if (svc.dataset.cardVariant === 'row') {
        svc.style.display = 'none';
      } else if (svc.dataset.cardVariant === 'card') {
        svc.style.display = '';
      }
    });

    btn.textContent = btn.dataset.labelTable || 'Tabelle';
    btn.setAttribute('aria-label', 'Zur Tabellenansicht wechseln');
  } else {
    // Switch to table layout
    container.classList.remove('grid', 'grid-cols-1', 'sm:grid-cols-2', 'lg:grid-cols-3', 'gap-4');
    container.classList.add('flex', 'flex-col');

    // Show table rows, hide cards
    services.forEach((svc) => {
      if (svc.dataset.cardVariant === 'row') {
        svc.style.display = '';
      } else if (svc.dataset.cardVariant === 'card') {
        svc.style.display = 'none';
      }
    });

    btn.textContent = btn.dataset.labelCards || 'Karten';
    btn.setAttribute('aria-label', 'Zur Kartenansicht wechseln');
  }
}

// Initialize when DOM is ready
document.addEventListener('DOMContentLoaded', initViewToggle);
