// Configuration publique du catalogue. La clé anon Supabase est conçue pour le navigateur
// et doit être protégée par les politiques RLS de la base. Ne jamais mettre de clé secrète d'administration ici.
window.SHOPLINOUS_CONFIG = Object.freeze({
  supabaseUrl: "", // URL du projet Supabase, ex. https://xxxx.supabase.co
  supabaseAnonKey: "" // clé publishable/anon publique du projet
});
