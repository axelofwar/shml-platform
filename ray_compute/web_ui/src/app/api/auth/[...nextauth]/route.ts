import NextAuth, { NextAuthOptions } from "next-auth"

const authOptions: NextAuthOptions = {
  providers: [
    {
      id: "authentik",
      name: "Authentik",
      type: "oauth",
      // Manually configure endpoints - PUBLIC URL for browser, INTERNAL for server
      issuer: `${process.env.AUTHENTIK_URL}/application/o/ray-compute/`,
      authorization: {
        url: `${process.env.NEXT_PUBLIC_AUTHENTIK_URL}/application/o/authorize/`,
        params: {
          scope: "openid email profile",
        }
      },
      token: `${process.env.AUTHENTIK_URL}/application/o/token/`,
      userinfo: `${process.env.AUTHENTIK_URL}/application/o/userinfo/`,
      // JWKS endpoint for JWT validation
      jwks_endpoint: `${process.env.AUTHENTIK_URL}/application/o/ray-compute/jwks/`,
      clientId: process.env.AUTHENTIK_CLIENT_ID || "ray-compute-api",
      clientSecret: process.env.AUTHENTIK_CLIENT_SECRET!,
      idToken: true,
      checks: ["state"],
      profile(profile) {
        return {
          id: profile.sub,
          name: profile.name || profile.preferred_username,
          email: profile.email,
          image: profile.picture,
        }
      },
    },
  ],
  debug: true,
  callbacks: {
    async jwt({ token, account, user }) {
      // Persist the OAuth access_token to the token right after signin
      if (account) {
        console.log('Storing OAuth access token in JWT');
        token.accessToken = account.access_token
        token.refreshToken = account.refresh_token
        token.expiresAt = account.expires_at
      }
      return token
    },
    async session({ session, token }) {
      // Send the raw OAuth access token to the client
      // This is the actual Authentik token, not a NextAuth JWT
      if (token.accessToken) {
        session.accessToken = token.accessToken as string
        console.log('Session has access token:', !!session.accessToken);
      } else {
        console.warn('No access token in JWT token object');
      }
      return session
    },
  },
  pages: {
    signIn: '/login',
  },
  session: {
    strategy: "jwt",
  },
}

const handler = NextAuth(authOptions)
export { handler as GET, handler as POST }
