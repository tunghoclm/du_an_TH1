(function () {
  'use strict';

  var navigation = document.getElementById('primary-navigation');
  var menuToggle = document.getElementById('header-menu-toggle');
  var navigationSpace = document.querySelector('.topbar-navigation');
  var moreButton = document.getElementById('more-menu-btn');
  var moreWrap = moreButton && moreButton.parentElement;
  var morePanel = document.getElementById('more-menu-popover');
  var overflowLinks = document.getElementById('nav-overflow-links');
  var primaryLinks = navigation ? Array.from(navigation.children).filter(function (item) { return item.matches('a.topbar-link'); }) : [];
  var overflowCopies = primaryLinks.map(function (link) {
    var copy = link.cloneNode(true);
    copy.className = link.classList.contains('active') ? 'active' : '';
    return copy;
  });
  var dropdowns = Array.from(document.querySelectorAll('[data-header-dropdown]')).map(function (wrap) {
    var button = wrap.querySelector('button[aria-controls]');
    return { wrap: wrap, button: button, panel: document.getElementById(button.getAttribute('aria-controls')) };
  });

  function setDropdown(dropdown, open) {
    if (!open && dropdown.panel.contains(document.activeElement)) dropdown.button.focus();
    dropdown.panel.hidden = !open;
    dropdown.button.setAttribute('aria-expanded', String(open));
    if (open && dropdown.button === moreButton) {
      var anchor = moreButton.getBoundingClientRect();
      var width = dropdown.panel.getBoundingClientRect().width;
      var top = Math.max(12, Math.min(anchor.bottom + 12, window.innerHeight - 160));
      dropdown.panel.style.position = 'fixed';
      dropdown.panel.style.top = top + 'px';
      dropdown.panel.style.left = Math.max(12, Math.min(anchor.right - width, window.innerWidth - width - 12)) + 'px';
      dropdown.panel.style.right = 'auto';
      dropdown.panel.style.maxHeight = Math.max(0, window.innerHeight - top - 12) + 'px';
    }
  }

  function fitNavigation() {
    if (!navigationSpace || !moreButton || !overflowLinks) return;
    var moreHadFocus = moreWrap.contains(document.activeElement);
    primaryLinks.forEach(function (link) { link.hidden = false; });
    overflowLinks.replaceChildren();
    overflowLinks.hidden = true;
    moreButton.classList.remove('active');
    moreWrap.hidden = true;
    var mobile = window.matchMedia('(max-width: 760px)').matches;

    var style = window.getComputedStyle(navigation);
    var edges = parseFloat(style.paddingLeft) + parseFloat(style.paddingRight) +
      parseFloat(style.borderLeftWidth) + parseFloat(style.borderRightWidth);
    var available = navigationSpace.clientWidth - edges;
    var widths = primaryLinks.map(function (link) { return link.getBoundingClientRect().width; });
    var used = widths.reduce(function (sum, width) { return sum + width; }, 0);
    if (mobile || used <= available) {
      morePanel.hidden = true;
      moreButton.setAttribute('aria-expanded', 'false');
      if (moreHadFocus) {
        var focusTarget = mobile ? menuToggle : (primaryLinks.find(function (link) { return link.classList.contains('active'); }) || primaryLinks[0]);
        if (focusTarget) focusTarget.focus({preventScroll:true});
      }
      return;
    }

    moreWrap.hidden = false;
    used += moreWrap.getBoundingClientRect().width;
    var visibleCount = primaryLinks.length;
    while (visibleCount > 0 && used > available) used -= widths[--visibleCount];

    primaryLinks.forEach(function (link, index) {
      if (index < visibleCount) return;
      if (link.contains(document.activeElement)) moreButton.focus({preventScroll:true});
      link.hidden = true;
      overflowLinks.appendChild(overflowCopies[index]);
      if (link.classList.contains('active')) moreButton.classList.add('active');
    });
    overflowLinks.hidden = visibleCount === primaryLinks.length;
  }

  var layoutPending = false;
  function scheduleNavigationLayout() {
    if (layoutPending) return;
    layoutPending = true;
    window.requestAnimationFrame(function () { layoutPending = false; fitNavigation(); });
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
    scheduleNavigationLayout();
  });
  if (navigationSpace && window.ResizeObserver) new ResizeObserver(scheduleNavigationLayout).observe(navigationSpace);
  if (document.fonts) document.fonts.ready.then(scheduleNavigationLayout);
  fitNavigation();
})();
