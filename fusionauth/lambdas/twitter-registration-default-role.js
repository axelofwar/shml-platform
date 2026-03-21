/**
 * FusionAuth Lambda: Twitter Registration - Assign Default Role
 *
 * PURPOSE: Automatically assign 'viewer' role to users registering via Twitter/X OAuth
 *
 * TRIGGER: Twitter (ExternalJWT) Identity Provider → User Reconcile Lambda
 *
 * PROBLEM: When users sign in with Twitter, FusionAuth creates a registration
 * but does NOT automatically assign the default role (isDefault: true).
 * This causes OAuth2-Proxy to receive empty roles claim, leading to:
 * - User is authenticated but has no roles
 * - Every role-auth check returns 403 Forbidden
 * - Effectively a broken login experience
 *
 * SOLUTION: This lambda runs during Twitter sign-in and adds the viewer role
 * to the user's OAuth2-Proxy registration before the JWT is issued.
 *
 * CONFIGURATION:
 * 1. Go to FusionAuth Admin → Settings → Lambdas → Add Lambda
 * 2. Name: "Twitter Registration - Assign Default Role"
 * 3. Type: "ExternalJWT Reconcile" (for Twitter ExternalJWT provider)
 * 4. Paste this code
 * 5. Go to Settings → Identity Providers → Twitter
 * 6. Select this lambda under "Reconcile lambda"
 * 7. Save
 *
 * @param {Object} user - The FusionAuth user object
 * @param {Object} registration - The registration being created/updated
 * @param {Object} jwt - The Twitter JWT/token claims
 */

function reconcile(user, registration, jwt) {
  // OAuth2-Proxy application ID (OAuth2-Proxy-rotation-1 in FusionAuth DB)
  var oauthProxyAppId = '50a4dc27-578a-47f1-a98e-1b9f47e2e81b';

  // Default role for new users
  var defaultRole = 'viewer';

  // Check if this is a registration for the OAuth2-Proxy app
  if (registration.applicationId === oauthProxyAppId) {

    // Initialize roles array if it doesn't exist
    if (!registration.roles) {
      registration.roles = [];
    }

    // Only add default role if user has no roles yet
    // This prevents overriding manually assigned roles
    if (registration.roles.length === 0) {
      registration.roles.push(defaultRole);

      // Log for debugging (visible in FusionAuth Event Log)
      console.info('Assigned default role "' + defaultRole + '" to Twitter user ' + (user.email || user.username || 'unknown') + ' for OAuth2-Proxy registration');
    }
  }
}
