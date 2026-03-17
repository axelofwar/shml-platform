/**
 * FusionAuth Lambda: JWT Populate - Include Roles Claim
 *
 * PURPOSE: Add user's application roles to the JWT id_token as a "roles" claim
 *
 * TRIGGER: JWT Populate Lambda (runs for EVERY token generation)
 *
 * PROBLEM: By default, FusionAuth does NOT include application roles in the JWT.
 * OAuth2-Proxy expects roles in the "roles" claim (configured via OAUTH2_PROXY_OIDC_GROUPS_CLAIM).
 * Without this lambda, the id_token has no roles claim, causing:
 * - OAuth redirect loops (if OAUTH2_PROXY_ALLOWED_GROUPS is enabled)
 * - Empty X-Auth-Request-Groups header passed to downstream services
 * - Role-based access control (role-auth middleware) fails
 *
 * SOLUTION: This lambda runs during token generation and adds the user's
 * application roles to the id_token as a "roles" array claim.
 *
 * CONFIGURATION:
 * 1. Go to FusionAuth Admin → Tenants → [Your Tenant] → Edit
 * 2. Scroll to "JWT" section
 * 3. Click "Id Token populate lambda" dropdown
 * 4. Select this lambda: "JWT Populate - Include Roles Claim"
 * 5. Save
 *
 * VERIFICATION:
 * 1. Sign in to platform
 * 2. Open browser DevTools → Application → Cookies
 * 3. Copy the JWT from cookie: _sfml_oauth2
 * 4. Decode at jwt.io - should see "roles": ["viewer"] in payload
 *
 * @param {Object} jwt - The JWT object being populated
 * @param {Object} user - The FusionAuth user
 * @param {Object} registration - The user's registration for this application
 */

function populate(jwt, user, registration) {
  // Only add roles if user has an active registration for this application
  if (registration && registration.roles) {
    // Add roles array to JWT claims
    // OAuth2-Proxy will read this as "groups" via OAUTH2_PROXY_OIDC_GROUPS_CLAIM
    jwt.roles = registration.roles;

    // Also add as comma-separated string for compatibility
    jwt.role = registration.roles.join(',');

    // Log for debugging (visible in FusionAuth Event Log)
    console.info('Added roles to JWT for user ' + user.email + ': ' + jwt.roles.join(', '));
  } else {
    // No registration or no roles - log warning
    console.warn('User ' + user.email + ' has no roles for application ' + jwt.aud);
    jwt.roles = [];
    jwt.role = '';
  }
}
