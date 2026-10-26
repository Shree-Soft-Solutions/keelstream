/**
 * KeelStream Client-Side Touchpoint & Attribution Tracker
 * Version: 1.0.0
 * 
 * Features:
 * - Deterministic capture of UTM parameters (utm_source, utm_medium, utm_campaign, utm_content, utm_term)
 * - Deterministic capture of ad click IDs (gclid, fbclid, msclkid, ttclid)
 * - Anonymous client ID and session ID generation and persistence
 * - Strict adherence to Do Not Track (DNT) and explicit consent choices
 * - Non-blocking beacon transmission to /api/v1/track
 */
(function (root, factory) {
  if (typeof define === 'function' && define.amd) {
    define([], factory);
  } else if (typeof module === 'object' && module.exports) {
    module.exports = factory();
  } else {
    root.KeelStream = factory();
  }
})(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  var STORAGE_KEYS = {
    CLIENT_ID: '_ks_cid',
    SESSION_ID: '_ks_sid',
    CONSENT: '_ks_consent',
    TOUCHPOINT_CACHE: '_ks_tp_cache'
  };

  var UTM_PARAMS = [
    'utm_source',
    'utm_medium',
    'utm_campaign',
    'utm_content',
    'utm_term'
  ];

  var CLICK_ID_PARAMS = [
    'gclid',     // Google Ads
    'fbclid',    // Meta / Facebook
    'msclkid',   // Microsoft Advertising
    'ttclid'     // TikTok Ads
  ];

  var defaultConfig = {
    tenantId: null,
    endpoint: '/api/v1/track',
    respectDNT: true,
    consent: null, // true, false, or null (unspecified)
    autoPageview: true,
    cookieDomain: null,
    cookieExpiresDays: 365
  };

  var config = Object.assign({}, defaultConfig);
  var currentUserTraits = {};
  var currentVerifiedIdentifier = null;
  var isInitialized = false;

  function safeGetStorage(storageType, key) {
    try {
      if (typeof window !== 'undefined' && window[storageType]) {
        return window[storageType].getItem(key);
      }
    } catch (e) {
      // Storage access blocked (e.g. private mode, cross-origin sandbox)
    }
    return null;
  }

  function safeSetStorage(storageType, key, value) {
    try {
      if (typeof window !== 'undefined' && window[storageType]) {
        window[storageType].setItem(key, value);
        return true;
      }
    } catch (e) {
      // Storage access blocked
    }
    return false;
  }

  function safeRemoveStorage(storageType, key) {
    try {
      if (typeof window !== 'undefined' && window[storageType]) {
        window[storageType].removeItem(key);
        return true;
      }
    } catch (e) {
      // Storage access blocked
    }
    return false;
  }

  function getCookie(name) {
    try {
      if (typeof document === 'undefined') return null;
      var nameEQ = name + '=';
      var ca = document.cookie.split(';');
      for (var i = 0; i < ca.length; i++) {
        var c = ca[i];
        while (c.charAt(0) === ' ') c = c.substring(1, c.length);
        if (c.indexOf(nameEQ) === 0) return decodeURIComponent(c.substring(nameEQ.length, c.length));
      }
    } catch (e) {}
    return null;
  }

  function setCookie(name, value, days, domain) {
    try {
      if (typeof document === 'undefined') return;
      var expires = '';
      if (days) {
        var date = new Date();
        date.setTime(date.getTime() + (days * 24 * 60 * 60 * 1000));
        expires = '; expires=' + date.toUTCString();
      }
      var domainString = domain ? '; domain=' + domain : '';
      document.cookie = name + '=' + encodeURIComponent(value) + expires + '; path=/; SameSite=Lax' + domainString;
    } catch (e) {}
  }

  function generateUUID() {
    if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
      return crypto.randomUUID();
    }
    return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, function (c) {
      var r = (Math.random() * 16) | 0;
      var v = c === 'x' ? r : (r & 0x3) | 0x8;
      return v.toString(16);
    });
  }

  function isDNTActive() {
    if (typeof navigator === 'undefined' && typeof window === 'undefined') return false;
    var dnt = (typeof navigator !== 'undefined' && (navigator.doNotTrack || navigator.msDoNotTrack)) ||
              (typeof window !== 'undefined' && window.doNotTrack);
    return dnt === '1' || dnt === 1 || dnt === 'yes';
  }

  function hasConsent() {
    // If explicit consent is set via API / stored choice, it takes precedence
    var storedConsent = safeGetStorage('localStorage', STORAGE_KEYS.CONSENT);
    if (storedConsent !== null) {
      return storedConsent === 'true';
    }
    if (config.consent !== null) {
      return config.consent === true;
    }
    // If respectDNT is enabled and browser has DNT active, consent is denied
    if (config.respectDNT && isDNTActive()) {
      return false;
    }
    // Default: consent permitted until revoked
    return true;
  }

  function parseQueryParams(url) {
    var params = {};
    try {
      var search = '';
      if (typeof url === 'string') {
        var qIdx = url.indexOf('?');
        if (qIdx !== -1) search = url.substring(qIdx);
      } else if (typeof window !== 'undefined' && window.location) {
        search = window.location.search;
      }
      if (search && search.length > 1) {
        var pairs = search.substring(1).split('&');
        for (var i = 0; i < pairs.length; i++) {
          var pair = pairs[i].split('=');
          var key = decodeURIComponent(pair[0]);
          var val = pair.length > 1 ? decodeURIComponent(pair[1].replace(/\+/g, ' ')) : '';
          params[key] = val;
        }
      }
    } catch (e) {}
    return params;
  }

  function getClientId() {
    var cid = safeGetStorage('localStorage', STORAGE_KEYS.CLIENT_ID) || getCookie(STORAGE_KEYS.CLIENT_ID);
    if (!cid && hasConsent()) {
      cid = 'ks_' + generateUUID();
      safeSetStorage('localStorage', STORAGE_KEYS.CLIENT_ID, cid);
      setCookie(STORAGE_KEYS.CLIENT_ID, cid, config.cookieExpiresDays, config.cookieDomain);
    }
    return cid;
  }

  function getSessionId() {
    var sid = safeGetStorage('sessionStorage', STORAGE_KEYS.SESSION_ID);
    if (!sid && hasConsent()) {
      sid = 'ks_ses_' + generateUUID();
      safeSetStorage('sessionStorage', STORAGE_KEYS.SESSION_ID, sid);
    }
    return sid;
  }

  function extractTouchpointData(url) {
    var qParams = parseQueryParams(url);
    var utmData = {};
    var clickIds = {};
    var primaryClickId = null;

    UTM_PARAMS.forEach(function (param) {
      if (qParams[param]) {
        utmData[param] = qParams[param];
      }
    });

    CLICK_ID_PARAMS.forEach(function (param) {
      if (qParams[param]) {
        clickIds[param] = qParams[param];
        if (!primaryClickId) {
          primaryClickId = qParams[param];
        }
      }
    });

    return {
      utm_source: utmData.utm_source || null,
      utm_medium: utmData.utm_medium || null,
      utm_campaign: utmData.utm_campaign || null,
      utm_content: utmData.utm_content || null,
      utm_term: utmData.utm_term || null,
      click_id: primaryClickId,
      click_ids: clickIds,
      url: typeof window !== 'undefined' && window.location ? window.location.href : (url || null),
      path: typeof window !== 'undefined' && window.location ? window.location.pathname : null,
      referrer: typeof document !== 'undefined' ? (document.referrer || null) : null
    };
  }

  function sendBeaconPayload(endpoint, payload) {
    var payloadString = JSON.stringify(payload);

    // Try navigator.sendBeacon
    if (typeof navigator !== 'undefined' && typeof navigator.sendBeacon === 'function') {
      try {
        var blob = new Blob([payloadString], { type: 'application/json' });
        var sent = navigator.sendBeacon(endpoint, blob);
        if (sent) return true;
      } catch (e) {
        // Fallback to fetch
      }
    }

    // Fallback to fetch
    if (typeof fetch === 'function') {
      try {
        fetch(endpoint, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: payloadString,
          keepalive: true
        }).catch(function () {});
        return true;
      } catch (e) {}
    }

    // Fallback to XMLHttpRequest
    if (typeof XMLHttpRequest !== 'undefined') {
      try {
        var xhr = new XMLHttpRequest();
        xhr.open('POST', endpoint, true);
        xhr.setRequestHeader('Content-Type', 'application/json');
        xhr.send(payloadString);
        return true;
      } catch (e) {}
    }

    return false;
  }

  var KeelStream = {
    version: '1.0.0',

    init: function (options) {
      if (options) {
        config = Object.assign({}, defaultConfig, options);
      }
      isInitialized = true;

      if (!hasConsent()) {
        return;
      }

      // Initialize persistent client ID and session ID
      getClientId();
      getSessionId();

      if (config.autoPageview) {
        this.track('pageview');
      }
    },

    setConsent: function (granted) {
      var isGranted = Boolean(granted);
      config.consent = isGranted;
      safeSetStorage('localStorage', STORAGE_KEYS.CONSENT, isGranted ? 'true' : 'false');

      if (!isGranted) {
        // Purge client and session identifiers upon explicit revocation
        safeRemoveStorage('localStorage', STORAGE_KEYS.CLIENT_ID);
        safeRemoveStorage('sessionStorage', STORAGE_KEYS.SESSION_ID);
        setCookie(STORAGE_KEYS.CLIENT_ID, '', -1, config.cookieDomain);
      } else {
        // Ensure identifiers are ready
        getClientId();
        getSessionId();
      }
    },

    hasConsent: function () {
      return hasConsent();
    },

    isDNTActive: function () {
      return isDNTActive();
    },

    getClientId: function () {
      return getClientId();
    },

    getSessionId: function () {
      return getSessionId();
    },

    getTouchpointData: function (url) {
      return extractTouchpointData(url);
    },

    identify: function (identifier, traits) {
      if (!identifier && !traits) return null;
      if (!hasConsent()) return null;

      currentVerifiedIdentifier = identifier || currentVerifiedIdentifier;
      if (traits && typeof traits === 'object') {
        currentUserTraits = Object.assign({}, currentUserTraits, traits);
      }

      return this.track('identify', {
        verified_identifier: currentVerifiedIdentifier,
        traits: currentUserTraits
      });
    },

    track: function (eventName, customProperties) {
      if (!hasConsent()) {
        return null;
      }

      var touchpoint = extractTouchpointData();
      var clientId = getClientId();
      var sessionId = getSessionId();

      var payload = {
        tenant_id: config.tenantId,
        anonymous_id: clientId,
        session_id: sessionId,
        event_name: eventName || 'custom_event',
        timestamp: new Date().toISOString(),
        url: touchpoint.url,
        path: touchpoint.path,
        referrer: touchpoint.referrer,
        utm_source: touchpoint.utm_source,
        utm_medium: touchpoint.utm_medium,
        utm_campaign: touchpoint.utm_campaign,
        utm_content: touchpoint.utm_content,
        utm_term: touchpoint.utm_term,
        click_id: touchpoint.click_id,
        click_ids: touchpoint.click_ids,
        verified_identifier: currentVerifiedIdentifier,
        user_traits: currentUserTraits,
        custom_properties: customProperties || {},
        consent_status: 'GRANTED'
      };

      sendBeaconPayload(config.endpoint, payload);
      return payload;
    },

    reset: function () {
      currentVerifiedIdentifier = null;
      currentUserTraits = {};
      safeRemoveStorage('localStorage', STORAGE_KEYS.CLIENT_ID);
      safeRemoveStorage('sessionStorage', STORAGE_KEYS.SESSION_ID);
      setCookie(STORAGE_KEYS.CLIENT_ID, '', -1, config.cookieDomain);
    }
  };

  return KeelStream;
});
