/**
 * FusionAuth Lambda: Google Registration - Assign Default Role
 *
 * PURPOSE: Automatically assign 'viewer' role to users registering via Google OAuth
 *
 * TRIGGER: Google Identity Provider → User Reconcile Lambda
 *
 * PROBLEM: When users sign in with Google, FusionAuth creates a registration
 * but does NOT automatically assign the default role (isDefault: true).
 * This causes OAuth2-Proxy to receive empty roles claim, leading to redirect loops.
 *
 * SOLUTION: This lambda runs during Google sign-in and adds the viewer role
 * to the user's OAuth2-Proxy registration before the JWT is issued.
 *
 * CONFIGURATION:
 * 1. Go to FusionAuth Admin → Settings → Lambdas → Add Lambda
 * 2. Name: "Google Registration - Assign Default Role"
 * 3. Type: "Google Reconcile"
 * 4. Paste this code
 * 5. Go to Settings → Identity Providers → Google
 * 6. Select this lambda under "Reconcile lambda"
 * 7. Save
 *
 * @param {Object} user - The FusionAuth user object
 * @param {Object} registration - The registration being created/updated
 * @param {Object} idToken - The Google ID token
 */

function reconcile(user, registration, idToken) {
  // OAuth2-Proxy application ID (from kickstart.json)
  var oauthProxyAppId = 'acda34f0-7cf2-40eb-9cba-7cb0048857d3';

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
      console.info('Assigned default role "' + defaultRole + '" to user ' + user.email + ' for OAuth2-Proxy registration');
    }
  }
}
