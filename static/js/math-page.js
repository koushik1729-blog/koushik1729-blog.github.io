(function () {
  function ensureHeadingId(el, fallbackPrefix) {
    if (el.id) {
      return el.id;
    }
    var value = (el.textContent || '').trim().toLowerCase();
    value = value.replace(/[^a-z0-9\s-]/g, '').replace(/\s+/g, '-');
    if (!value) {
      value = fallbackPrefix;
    }
    el.id = value;
    return value;
  }

  function buildMathToc() {
    var article = document.querySelector('[data-math-article]');
    var tocRoot = document.getElementById('math-generated-toc');
    var layout = article ? article.closest('.math-layout') : null;
    if (!article || !tocRoot) {
      return;
    }

    var headings = article.querySelectorAll('h1, h2, h3');
    if (!headings.length) {
      tocRoot.parentElement.style.display = 'none';
      if (layout) {
        layout.classList.add('math-layout-no-toc');
      }
      return;
    }

    if (layout) {
      layout.classList.remove('math-layout-no-toc');
    }

    var links = [];
    headings.forEach(function (heading, index) {
      var id = ensureHeadingId(heading, 'section-' + (index + 1));
      var link = document.createElement('a');
      link.href = '#' + id;
      link.textContent = heading.textContent || 'Section ' + (index + 1);
      link.className = 'toc-' + heading.tagName.toLowerCase();
      tocRoot.appendChild(link);
      links.push({ id: id, link: link });
    });

    var observer = new IntersectionObserver(
      function (entries) {
        entries.forEach(function (entry) {
          var target = links.find(function (item) {
            return item.id === entry.target.id;
          });
          if (!target) {
            return;
          }
          if (entry.isIntersecting) {
            links.forEach(function (item) {
              item.link.classList.remove('active');
            });
            target.link.classList.add('active');
          }
        });
      },
      { rootMargin: '-15% 0px -70% 0px', threshold: [0, 1] }
    );

    headings.forEach(function (h) {
      observer.observe(h);
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', buildMathToc);
  } else {
    buildMathToc();
  }
})();
