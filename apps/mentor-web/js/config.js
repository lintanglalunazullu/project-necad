/**
 * Aksaraku — Konfigurasi Terpusat
 *
 * Smart Auto-Detect Environment:
 * - Localhost / File : http://localhost:3000
 * - Production       : https://api.<base-domain> (contoh: https://api.smpn2cibungbulang.sch.id)
 *
 * Tidak perlu edit manual saat switch antara laptop dan server VPS!
 */
(function (global) {
  function detectApiBaseUrl() {
    // 1. Cek jika ada manual override dari window
    if (global.__AKSARAKU_API_OVERRIDE__) {
      return global.__AKSARAKU_API_OVERRIDE__;
    }

    var hostname = global.location ? global.location.hostname : '';
    var protocol = global.location ? global.location.protocol : 'http:';

    // 2. Lingkungan Local Development atau dibuka via file manager
    if (!hostname || hostname === 'localhost' || hostname === '127.0.0.1' || protocol === 'file:') {
      return 'http://localhost:3000';
    }

    // 3. Lingkungan Server / Subdomain Production
    // Contoh: mentor.smpn2cibungbulang.sch.id -> api.smpn2cibungbulang.sch.id
    var baseDomain = hostname.replace(/^(mentor|www)\./i, '');
    var apiProtocol = protocol === 'http:' ? 'http:' : 'https:';
    return apiProtocol + '//api.' + baseDomain;
  }

  global.AKSARAKU_CONFIG = Object.freeze({
    // URL backend API (services/api) — otomatis terdeteksi
    API_BASE_URL: detectApiBaseUrl(),

    // Supabase project credentials
    SUPABASE_URL: 'https://pwohquppbydpycpqwxtg.supabase.co',
    SUPABASE_ANON_KEY:
      'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InB3b2hxdXBwYnlkcHljcHF3eHRnIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODU1MjYyNTUsImV4cCI6MjEwMTEwMjI1NX0.QUmKNTzaw88NZqb7ihR9Mgm7laJzm6_-M7Ktz0hNcGU',
  });
})(typeof window !== 'undefined' ? window : this);
