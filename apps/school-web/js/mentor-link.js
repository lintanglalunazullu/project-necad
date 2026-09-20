/**
 * Aksaraku AI Mentor — Link Resolver Cerdas
 *
 * Mengarahkan tombol .ai-float secara dinamis:
 * - Localhost dev : http://localhost:8081
 * - Production    : https://mentor.smpn2cibungbulang.sch.id (atau subdomain mentor domain aktif)
 * - Offline file  : ../mentor-web/index.html
 */
(function () {
  function getMentorTargetUrl() {
    var loc = window.location;
    var hostname = loc.hostname;
    var protocol = loc.protocol;

    // 1. Localhost development
    if (hostname === 'localhost' || hostname === '127.0.0.1') {
      return protocol + '//' + hostname + ':8081';
    }

    // 2. Vercel Single-Project Deployment
    if (hostname.endsWith('.vercel.app')) {
      return protocol + '//' + hostname + '/mentor';
    }

    // 3. Direct file opening (tanpa web server)
    if (protocol === 'file:' || !hostname) {
      return loc.pathname.indexOf('/pages/') !== -1
        ? '../../mentor-web/index.html'
        : '../mentor-web/index.html';
    }

    // 4. Production server (Subdomain mentor)
    // Contoh: smpn2cibungbulang.sch.id -> https://mentor.smpn2cibungbulang.sch.id
    // www.smpn2cibungbulang.sch.id -> https://mentor.smpn2cibungbulang.sch.id
    var baseDomain = hostname.replace(/^(www|portal|web)\./i, '');
    var targetProtocol = protocol === 'http:' ? 'http:' : 'https:';
    return targetProtocol + '//mentor.' + baseDomain;
  }

  function applyMentorLinks() {
    var targetUrl = getMentorTargetUrl();
    var links = document.querySelectorAll('a.ai-float');
    for (var i = 0; i < links.length; i++) {
      links[i].href = targetUrl;
    }
  }

  // Jalankan sesegera mungkin & saat DOM siap
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', applyMentorLinks);
  } else {
    applyMentorLinks();
  }

  // Delegasi event klik sebagai pengaman tambahan (jika diklik sebelum href terupdate)
  document.addEventListener('click', function (e) {
    var link = e.target.closest('a.ai-float');
    if (link) {
      link.href = getMentorTargetUrl();
    }
  });
})();
