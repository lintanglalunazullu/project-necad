/**
 * Aksaraku — Konfigurasi Terpusat
 *
 * Development : API_BASE_URL = 'http://localhost:3000'
 * Production  : Ganti API_BASE_URL ke URL deployment services/api
 *               (lihat docs/DEPLOYMENT.md)
 */
window.AKSARAKU_CONFIG = Object.freeze({
  // URL backend API (services/api)
  // Development: 'http://localhost:3000'
  // Production : 'https://api.domain-anda.com'
  API_BASE_URL: 'http://localhost:3000',

  // Supabase project credentials
  SUPABASE_URL: 'https://pwohquppbydpycpqwxtg.supabase.co',
  SUPABASE_ANON_KEY: 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InB3b2hxdXBwYnlkcHljcHF3eHRnIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODU1MjYyNTUsImV4cCI6MjEwMTEwMjI1NX0.QUmKNTzaw88NZqb7ihR9Mgm7laJzm6_-M7Ktz0hNcGU',
});
