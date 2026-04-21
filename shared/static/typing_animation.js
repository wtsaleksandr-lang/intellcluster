/**
 * Placeholder typing animation — cycles through example prompts when input is empty/unfocused.
 * Stops on focus, resumes on blur if still empty.
 *
 * Usage:
 *   <textarea id="inp" data-typing="phronesis" placeholder="..."></textarea>
 *   <script src="/static/typing_animation.js"></script>
 *
 * Data attribute controls which preset library:
 *   data-typing="phronesis" or data-typing="synthesis"
 */

const TYPING_PRESETS = {
  phronesis: [
    "Should I buy Tesla Model 3 or Mach-E for commuting? Budget $45k, range matters most.",
    "Compare HubSpot, Salesforce, and Pipedrive for a 10-person sales team.",
    "Stay at current job ($120k stable) vs join startup ($90k + equity) vs freelance ($150k variable)?",
    "Best laptop under $1500 for software development: MacBook Air M3, ThinkPad X1, or Framework 16?",
    "Content marketing + SEO vs paid ads vs cold outreach for a bootstrapped SaaS?",
    "30-year fixed at 6.5% vs 5/1 ARM at 5.8% vs 15-year fixed at 5.9% for a $400k home?",
    "Which freight forwarder for oversized cargo from China to EU: Flexport, Freightos, or local broker?",
    "3-day full body lifting vs 5-day push/pull/legs vs daily HIIT for weight loss + muscle?",
  ],
  synthesis: [
    "Analyze the current state of the B2B SaaS pricing landscape and what's working in 2026.",
    "What are the most effective customer acquisition strategies for bootstrapped founders?",
    "Deep dive into the freight forwarding industry — trends, margins, and emerging competition.",
    "Research the impact of AI-driven cost pressures on enterprise software pricing.",
    "How are leading companies structuring their AI research teams? What roles are essential?",
    "What does the market expect from the next generation of AI agents, and where are the gaps?",
    "Analyze the most successful productivity tools launched since 2024 and what made them work.",
    "Research the pros and cons of building on Cloudflare Workers vs AWS Lambda for SaaS.",
  ],
};

(function() {
  const elements = document.querySelectorAll('[data-typing]');
  elements.forEach(initTyping);

  function initTyping(el) {
    const library = el.dataset.typing;
    const prompts = TYPING_PRESETS[library] || [];
    if (!prompts.length) return;

    // Shuffle so each page load is different
    const queue = [...prompts].sort(() => Math.random() - 0.5);
    let idx = 0;
    let state = 'typing'; // typing | pausing | deleting
    let charIdx = 0;
    let timer = null;
    let active = true;

    // Replace the native placeholder behavior with our animated value via a sibling overlay
    const overlay = document.createElement('div');
    overlay.setAttribute('aria-hidden', 'true');
    Object.assign(overlay.style, {
      position: 'absolute',
      pointerEvents: 'none',
      color: 'var(--text-dim)',
      whiteSpace: 'pre-wrap',
      overflow: 'hidden',
      userSelect: 'none',
    });
    // Position overlay to match the textarea's content box
    function positionOverlay() {
      const rect = el.getBoundingClientRect();
      const style = window.getComputedStyle(el);
      Object.assign(overlay.style, {
        left: el.offsetLeft + parseFloat(style.paddingLeft) + 'px',
        top: el.offsetTop + parseFloat(style.paddingTop) + 'px',
        width: (rect.width - parseFloat(style.paddingLeft) - parseFloat(style.paddingRight)) + 'px',
        fontSize: style.fontSize,
        fontFamily: style.fontFamily,
        lineHeight: style.lineHeight,
        letterSpacing: style.letterSpacing,
      });
    }

    // Insert overlay into the same parent as the textarea (positioning relative)
    const parent = el.parentElement;
    if (getComputedStyle(parent).position === 'static') parent.style.position = 'relative';
    parent.appendChild(overlay);
    // Clear native placeholder so only overlay shows
    el.dataset.originalPlaceholder = el.placeholder || '';
    el.placeholder = '';

    // Hide overlay when textarea has content or is focused
    function updateVisibility() {
      const hasContent = el.value.trim().length > 0;
      const isFocused = document.activeElement === el;
      overlay.style.display = (hasContent || isFocused) ? 'none' : 'block';
      if (hasContent || isFocused) {
        active = false;
        if (timer) clearTimeout(timer);
      } else {
        if (!active) {
          active = true;
          tick();
        }
      }
    }

    function tick() {
      if (!active) return;
      positionOverlay();
      const current = queue[idx % queue.length];

      if (state === 'typing') {
        charIdx++;
        overlay.textContent = current.slice(0, charIdx);
        if (charIdx >= current.length) {
          state = 'pausing';
          timer = setTimeout(tick, 2200);
          return;
        }
        // Vary typing speed for naturalness
        const delay = 30 + Math.random() * 35;
        timer = setTimeout(tick, delay);
      } else if (state === 'pausing') {
        state = 'deleting';
        timer = setTimeout(tick, 50);
      } else if (state === 'deleting') {
        charIdx -= 2;
        if (charIdx < 0) charIdx = 0;
        overlay.textContent = current.slice(0, charIdx);
        if (charIdx === 0) {
          idx++;
          state = 'typing';
          timer = setTimeout(tick, 400);
          return;
        }
        timer = setTimeout(tick, 18);
      }
    }

    el.addEventListener('focus', updateVisibility);
    el.addEventListener('blur', updateVisibility);
    el.addEventListener('input', updateVisibility);
    window.addEventListener('resize', positionOverlay);

    positionOverlay();
    updateVisibility();
    tick();
  }
})();
