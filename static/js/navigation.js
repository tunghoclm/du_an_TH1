(function () {
  'use strict';

  var navigation = document.getElementById('primary-navigation');
  var menuToggle = document.getElementById('header-menu-toggle');
  var dropdowns = Array.from(document.querySelectorAll('[data-header-dropdown]')).map(function (wrap) {
    var button = wrap.querySelector('button[aria-controls]');
    return { wrap: wrap, button: button, panel: document.getElementById(button.getAttribute('aria-controls')) };
  });

  function setDropdown(dropdown, open) {
    dropdown.panel.hidden = !open;
    dropdown.button.setAttribute('aria-expanded', String(open));
  }

  function closeDropdowns(except) {
    dropdowns.forEach(function (dropdown) {
      if (dropdown !== except) setDropdown(dropdown, false);
    });
  }

  function closeMobileMenu() {
    if (!navigation || !menuToggle) return;
    navigation.classList.remove('is-open');
    menuToggle.setAttribute('aria-expanded', 'false');
    menuToggle.setAttribute('aria-label', 'Mở menu điều hướng');
  }

  dropdowns.forEach(function (dropdown) {
    dropdown.button.addEventListener('click', function () {
      var open = dropdown.panel.hidden;
      closeDropdowns(dropdown);
      setDropdown(dropdown, open);
    });
  });

  if (menuToggle && navigation) {
    menuToggle.addEventListener('click', function () {
      var open = navigation.classList.toggle('is-open');
      menuToggle.setAttribute('aria-expanded', String(open));
      menuToggle.setAttribute('aria-label', open ? 'Đóng menu điều hướng' : 'Mở menu điều hướng');
      closeDropdowns();
    });
  }

  document.addEventListener('click', function (event) {
    dropdowns.forEach(function (dropdown) {
      if (!dropdown.wrap.contains(event.target)) setDropdown(dropdown, false);
    });
    if (navigation && menuToggle && !navigation.contains(event.target) && !menuToggle.contains(event.target)) {
      closeMobileMenu();
    }
  });

  document.addEventListener('keydown', function (event) {
    if (event.key !== 'Escape') return;
    var openDropdown = dropdowns.find(function (dropdown) { return !dropdown.panel.hidden; });
    closeDropdowns();
    if (openDropdown) {
      openDropdown.button.focus();
    } else if (navigation && navigation.classList.contains('is-open')) {
      closeMobileMenu();
      menuToggle.focus();
    }
  });

  window.addEventListener('resize', function () {
    closeDropdowns();
    if (window.innerWidth > 760) closeMobileMenu();
  });
})();
