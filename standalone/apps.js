/**
 * Fallback hub app registry.
 *
 * Source of truth is app/apps_manifest.py via GET /api/apps.
 * The hub loads that API on boot. Keep this file as an offline/dev fallback only.
 * When adding a tool: update apps_manifest.py (+ register_apps.py), not only this file.
 */
window.IMPECT_APP_GROUPS = window.IMPECT_APP_GROUPS || [];
window.IMPECT_APPS = window.IMPECT_APPS || [];
