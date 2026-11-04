(() => {
  "use strict";
  const root = document.querySelector("[data-shop-page]");
  if (!root) return;
  const page = root.dataset.shopPage;
  const cfg = window.SHOPLINOUS_CONFIG || {};
  const fields = "id,slug,market_code,name,short_description,description,category_slug,price,currency,image_urls,published_at";
  const cartKey = "shoplinous_cart_v1";
  const marketKey = "shoplinous_market_v1";
  const getMarket = () => { try { return localStorage.getItem(marketKey) || "CI"; } catch (_) { return "CI"; } };
  const setMarket = value => { try { localStorage.setItem(marketKey, value); } catch (_) {} };
  const el = (tag, cls, value) => {
    const node = document.createElement(tag);
    if (cls) node.className = cls;
    if (value !== undefined) node.textContent = value;
    return node;
  };
  const link = (href, label, cls) => {
    const a = el("a", cls, label); a.href = href; return a;
  };
  const message = (title, detail) => {
    const box = el("section", "shop-message");
    box.append(el("strong", "", title), el("p", "", detail));
    root.replaceChildren(box);
  };
  const money = (amount, currency) => {
    try { return new Intl.NumberFormat("fr-FR", {style:"currency",currency}).format(Number(amount)); }
    catch (_) { return Number(amount).toFixed(2) + " " + currency; }
  };
  const imageUrl = (urls) => Array.isArray(urls) ? urls.find(u => typeof u === "string" && /^https:\/\//i.test(u)) : null;
  const getCart = () => {
    try {
      const value = JSON.parse(localStorage.getItem(cartKey) || "[]");
      return Array.isArray(value) ? value.filter(x => x && typeof x.id === "string" && Number.isInteger(x.qty) && x.qty > 0) : [];
    } catch (_) { return []; }
  };
  const saveCart = (items) => { try { localStorage.setItem(cartKey, JSON.stringify(items)); } catch (_) {} };
  const api = async (query) => {
    if (!/^https:\/\//i.test(cfg.supabaseUrl || "") || !(cfg.supabaseAnonKey || "").trim()) {
      throw new Error("catalogue_not_configured");
    }
    const base = cfg.supabaseUrl.replace(/\/$/, "");
    const response = await fetch(base + "/rest/v1/storefront_products?" + query, {
      headers: { apikey: cfg.supabaseAnonKey, accept: "application/json" }
    });
    if (!response.ok) throw new Error("catalogue_unavailable");
    return response.json();
  };
  const productUrl = (slug, market) => "produit.html?slug=" + encodeURIComponent(slug) + "&market=" + encodeURIComponent(market);
  const makeCard = product => {
    const card = el("article", "shop-card");
    const src = imageUrl(product.image_urls);
    if (src) { const img = el("img"); img.src = src; img.alt = product.name; img.loading = "lazy"; card.append(img); }
    const body = el("div", "shop-card-body");
    body.append(el("span", "shop-badge", product.category_slug.replace(/-/g," ")));
    body.append(el("h2", "", product.name));
    body.append(el("p", "", product.short_description || "Découvrir ce produit."));
    body.append(el("strong", "shop-price", money(product.price, product.currency)));
    body.append(link(productUrl(product.slug, product.market_code), "Voir le produit ↗", "shop-link"));
    card.append(body); return card;
  };
  const renderCatalog = async () => {
    root.replaceChildren(el("div","shop-message","Chargement du catalogue…"));
    try {
      const products = await api("select=" + encodeURIComponent(fields) + "&order=published_at.desc&limit=100");
      const heading = el("div","shop-heading");
      const left = el("div");
      left.append(el("div","shop-eyebrow","La sélection vérifiée"),el("h1","","Tous nos produits"),el("p","shop-muted","Les produits affichés sont ceux qui sont publiés et dont les contrôles requis sont encore valides."));
      heading.append(left);
      const controls = el("div","shop-controls");
      const market = el("select","shop-select"); market.setAttribute("aria-label","Choisir le pays de livraison");
      const markets = [...new Set(products.map(p=>p.market_code))].sort();
      markets.forEach(code=>{const o=el("option");o.value=code;o.textContent="Livraison : "+code;market.append(o);});
      if(markets.includes(getMarket())) market.value=getMarket(); else if(markets.length) {market.value=markets[0];setMarket(markets[0]);}
      const search = el("input","shop-input"); search.type="search"; search.placeholder="Rechercher un produit…"; search.setAttribute("aria-label","Rechercher un produit");
      const category = el("select","shop-select"); category.setAttribute("aria-label","Filtrer par catégorie");
      const all = el("option"); all.value=""; all.textContent="Toutes les catégories"; category.append(all);
      [...new Set(products.map(p=>p.category_slug))].sort().forEach(c=>{const o=el("option");o.value=c;o.textContent=c.replace(/-/g," ");category.append(o);});
      controls.append(search,category,market);
      const count=el("p","shop-muted",""); const grid=el("div","shop-grid");
      const empty=el("div","shop-message",""); empty.hidden=true;
      const draw=()=>{
        const term=search.value.trim().toLocaleLowerCase("fr");
        const filtered=products.filter(p=>(p.market_code===market.value)&&(!category.value||p.category_slug===category.value)&&(!term||(p.name+" "+p.short_description+" "+p.description).toLocaleLowerCase("fr").includes(term)));
        count.textContent=filtered.length+" produit(s)";
        grid.replaceChildren(...filtered.map(makeCard));
        empty.hidden=filtered.length>0;
        if (!filtered.length) empty.textContent=products.length ? "Aucun produit ne correspond à cette recherche." : "Notre catalogue est en préparation. Les produits apparaîtront après validation des fournisseurs, des stocks et des livraisons.";
      };
      search.addEventListener("input",draw);category.addEventListener("change",draw);market.addEventListener("change",()=>{setMarket(market.value);draw();});
      draw(); root.replaceChildren(heading,controls,count,grid,empty);
    } catch (err) {
      message("Catalogue pas encore connecté","La vitrine est prête, mais la connexion publique Supabase doit encore être configurée. Aucun produit fictif ne sera affiché.");
    }
  };
  const renderProduct = async () => {
    const slug = new URLSearchParams(location.search).get("slug");
    if (!slug) { message("Produit introuvable","Choisissez un produit depuis le catalogue."); return; }
    try {
      const market = new URLSearchParams(location.search).get("market") || getMarket();
      const rows = await api("select="+encodeURIComponent(fields)+"&slug=eq."+encodeURIComponent(slug)+"&market_code=eq."+encodeURIComponent(market)+"&limit=1");
      const p=rows[0]; if(!p){message("Produit indisponible","Cette référence n'est plus publiée ou ses vérifications doivent être renouvelées.");return;}
      const wrap=el("div","shop-product"),gallery=el("div","shop-gallery"),detail=el("div","shop-detail");
      const urls=(p.image_urls||[]).filter(u=>typeof u==="string"&&/^https:\/\//i.test(u));
      const main=el("img");main.src=urls[0]||"";main.alt=p.name;main.loading="eager";gallery.append(main);
      if(urls.length>1){const thumbs=el("div","shop-thumbs");urls.forEach((u,i)=>{const b=el("button");b.type="button";b.setAttribute("aria-label","Voir image "+(i+1));const im=el("img");im.src=u;im.alt="";b.append(im);b.addEventListener("click",()=>{main.src=u;});thumbs.append(b);});gallery.append(thumbs);}
      detail.append(link("catalogue.html","← Retour au catalogue","shop-breadcrumb"));
      detail.append(el("div","shop-eyebrow",p.category_slug.replace(/-/g," ")));
      detail.append(el("h1","",p.name));
      detail.append(el("div","shop-price",money(p.price,p.currency)));
      detail.append(el("p","",p.short_description||""));
      detail.append(el("p","",p.description||"Informations détaillées à venir."));
      detail.append(el("p","shop-muted","Marché sélectionné : "+p.market_code));
      const qtyWrap=el("div","shop-qty"),qtyLabel=el("label","","Quantité"),qty=el("input");qty.type="number";qty.min="1";qty.max="5";qty.value="1";qtyLabel.append(qty);qtyWrap.append(qtyLabel);
      const add=el("button","shop-action","Ajouter au panier");add.type="button";
      add.addEventListener("click",()=>{
        const n=Math.max(1,Math.min(5,Number.parseInt(qty.value,10)||1));
        const cart=getCart();
        if(cart.some(x=>x.market && x.market!==p.market_code)){add.textContent="Videz le panier pour changer de pays";return;}
        const existing=cart.find(x=>x.id===p.id);
        if(existing)existing.qty=Math.min(5,existing.qty+n);else cart.push({id:p.id,slug:p.slug,market:p.market_code,qty:n});
        saveCart(cart);add.textContent="Ajouté au panier ✓";setTimeout(()=>{add.textContent="Ajouter au panier";},1600);
      });
      detail.append(qtyWrap,add,el("p","shop-footer-note","L'ajout au panier ne réserve pas le stock et ne déclenche aucun paiement."));
      wrap.append(gallery,detail);root.replaceChildren(wrap);
    } catch (_) { message("Fiche produit indisponible","La connexion au catalogue n'est pas encore configurée ou la référence n'est plus publiée."); }
  };
  const renderCart = async () => {
    const cart=getCart();
    if(!cart.length){message("Votre panier est vide","Parcourez le catalogue pour ajouter vos découvertes.");root.append(link("catalogue.html","Découvrir le catalogue","shop-link"));return;}
    try{
      const ids=cart.map(x=>x.id).filter(id=>/^[0-9a-f-]{36}$/i.test(id));
      if(!ids.length){saveCart([]);message("Votre panier est vide","Ajoutez des produits depuis le catalogue.");return;}
      const rows=await api("select="+encodeURIComponent(fields)+"&id=in.("+ids.join(",")+")");
      const available=cart.map(item=>({...item,product:rows.find(p=>p.id===item.id)})).filter(x=>x.product);
      saveCart(available.map(({id,slug,qty,market})=>({id,slug,qty,market})));
      if(!available.length){message("Panier à actualiser","Les références précédemment ajoutées ne sont plus disponibles. Retournez au catalogue.");return;}
      const heading=el("div","shop-heading");heading.append(el("div","",""),el("div","shop-eyebrow","Votre sélection"));
      const list=el("section","shop-panel"),sum=el("aside","shop-cart-summary");
      available.forEach(item=>{
        const row=el("article","shop-cart-row"),src=imageUrl(item.product.image_urls);
        if(src){const im=el("img");im.src=src;im.alt=item.product.name;row.append(im);}else row.append(el("div"));
        const info=el("div");info.append(el("h3","",item.product.name),el("p","",money(item.product.price,item.product.currency)));
        const qty=el("input");qty.type="number";qty.min="1";qty.max="5";qty.value=String(item.qty);qty.setAttribute("aria-label","Quantité pour "+item.product.name);
        qty.addEventListener("change",()=>{const n=Math.max(1,Math.min(5,Number.parseInt(qty.value,10)||1));const c=getCart();const target=c.find(x=>x.id===item.id);if(target)target.qty=n;saveCart(c);renderCart();});
        const remove=el("button","shop-link","Retirer");remove.type="button";remove.addEventListener("click",()=>{saveCart(getCart().filter(x=>x.id!==item.id));renderCart();});
        const actions=el("div");actions.append(qty,remove);row.append(info,actions);list.append(row);
      });
      const markets=[...new Set(available.map(x=>x.product.market_code))];
      if(markets.length>1) sum.append(el("p","shop-muted","Attention : votre panier contient plusieurs marchés. Séparez les pays avant de commander."));
      const currencies=[...new Set(available.map(x=>x.product.currency))];
      sum.append(el("div","shop-muted","Sous-total indicatif"));
      if(currencies.length===1 && markets.length===1){const total=available.reduce((n,x)=>n+Number(x.product.price)*x.qty,0);sum.append(el("strong","",money(total,currencies[0])));}
      else sum.append(el("strong","","Plusieurs devises"),el("p","shop-muted","Le total ne peut pas être calculé tant que les devises ne sont pas harmonisées."));
      const checkout=el("button","shop-action","Commander");checkout.type="button";checkout.disabled=true;
      sum.append(checkout,el("p","shop-footer-note","Le paiement et la création de commande ne sont pas encore activés. Le bouton restera désactivé jusqu'à la mise en place du serveur de commande sécurisé et du paiement Sandbox."));
      root.replaceChildren(heading,list,sum);
    }catch(_){message("Panier momentanément inaccessible","Impossible de revalider les produits. Réessayez lorsque la connexion au catalogue sera disponible.");}
  };
  if(page==="catalogue") renderCatalog();
  else if(page==="produit") renderProduct();
  else if(page==="panier") renderCart();
})();