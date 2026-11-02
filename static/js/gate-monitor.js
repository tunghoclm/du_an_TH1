(function () {
    'use strict';
    const clock = document.getElementById('gate-live-clock');
    const consolePanel = document.getElementById('gate-console');
    const expandButton = document.getElementById('gate-fullscreen');
    const restoreButton = document.getElementById('gate-restore');

    function tick() {
        if (clock) {
            const now = new Date();
            clock.textContent = now.toLocaleTimeString('vi-VN') + ' · ' + now.toLocaleDateString('vi-VN');
            clock.dateTime = now.toISOString();
        }
    }
    let timer;
    function startClock() {
        tick();
        window.clearInterval(timer);
        timer = window.setInterval(tick, 1000);
    }
    startClock();
    window.addEventListener('pageshow', startClock);
    window.addEventListener('pagehide', () => window.clearInterval(timer));

    if (!consolePanel || !expandButton || !restoreButton) return;
    function setExpanded(expanded) {
        consolePanel.classList.toggle('is-expanded', expanded);
        document.body.classList.toggle('gate-console-expanded', expanded);
        expandButton.setAttribute('aria-pressed', String(expanded));
        restoreButton.hidden = !expanded;
        (expanded ? restoreButton : expandButton).focus();
    }
    expandButton.addEventListener('click', () => {
        setExpanded(!consolePanel.classList.contains('is-expanded'));
    });
    restoreButton.addEventListener('click', () => setExpanded(false));
    document.addEventListener('keydown', event => {
        if (event.key === 'Escape' && consolePanel.classList.contains('is-expanded')) {
            setExpanded(false);
        }
    });
})();
