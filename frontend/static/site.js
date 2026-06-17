(function () {
  const FALLBACK_PRODUCT_NAME = "ResearchPigeon";

  function applyProductName(productName) {
    const name = productName || FALLBACK_PRODUCT_NAME;
    document.querySelectorAll(".product-name-text, .product-name-slot").forEach(function (el) {
      el.textContent = name;
    });
    const suffix = document.body.getAttribute("data-document-title");
    document.title = suffix ? suffix + " - " + name : name;
  }

  async function initSiteBranding() {
    try {
      const response = await fetch("/site-config");
      if (!response.ok) {
        applyProductName(FALLBACK_PRODUCT_NAME);
        return;
      }
      const payload = await response.json();
      applyProductName(payload.product_name);
    } catch (_error) {
      applyProductName(FALLBACK_PRODUCT_NAME);
    }
  }

  initSiteBranding();
})();
