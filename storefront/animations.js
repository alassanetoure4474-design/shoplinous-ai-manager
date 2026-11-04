(() => {
  "use strict";
  const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const steps = [
    {title:"Commande préparée",detail:"Le client vérifie son panier et choisit son pays de livraison.",status:"Étape 1 sur 4"},
    {title:"Paiement sécurisé GeniusPay",detail:"Le serveur prépare une session de paiement de test et associe une référence unique à la commande.",status:"Étape 2 sur 4"},
    {title:"Notification vérifiée",detail:"Le serveur vérifie la signature, le montant, la devise et la référence. Un simple retour du navigateur ne suffit pas.",status:"Étape 3 sur 4"},
    {title:"Confirmation sécurisée",detail:"La commande est marquée comme payée uniquement après validation de la notification par le serveur. Le client reçoit ensuite sa confirmation.",status:"Étape 4 sur 4"}
  ];
  const flow = document.querySelector("[data-payment-flow]");
  if (flow) {
    const title = flow.querySelector("[data-flow-title]");
    const detail = flow.querySelector("[data-flow-detail]");
    const status = flow.querySelector("[data-flow-status]");
    const nodes = [...flow.querySelectorAll("[data-flow-step]")];
    const next = flow.querySelector("[data-flow-next]");
    const reset = flow.querySelector("[data-flow-reset]");
    let current = 0;
    const render = () => {
      const step = steps[current];
      title.textContent = step.title;
      detail.textContent = step.detail;
      status.textContent = step.status;
      nodes.forEach((node, index) => {
        node.classList.toggle("is-current", index === current);
        node.classList.toggle("is-complete", index < current);
        node.setAttribute("aria-current", index === current ? "step" : "false");
      });
      next.disabled = current === steps.length - 1;
      next.textContent = current === steps.length - 1 ? "Parcours terminé" : "Étape suivante";
      reset.hidden = current === 0;
    };
    next.addEventListener("click", () => { if (current < steps.length - 1) { current += 1; render(); } });
    reset.addEventListener("click", () => { current = 0; render(); });
    render();
  }
  document.documentElement.classList.add("motion-ready");
  const revealItems = document.querySelectorAll("[data-reveal]");
  if (reduceMotion || !("IntersectionObserver" in window)) {
    revealItems.forEach(item => item.classList.add("is-visible"));
  } else {
    const observer = new IntersectionObserver(entries => {
      entries.forEach(entry => {
        if (entry.isIntersecting) {
          entry.target.classList.add("is-visible");
          observer.unobserve(entry.target);
        }
      });
    }, {threshold: 0.12});
    revealItems.forEach(item => observer.observe(item));
  }
})();