"use client";

import { useEffect, Suspense, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";

function AuthSuccessContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [mounted, setMounted] = useState(false);

  // Ensure component is mounted on client side
  useEffect(() => {
    setMounted(true);
  }, []);

  useEffect(() => {
    if (!mounted) return;

    const processTokens = () => {
      console.log("AuthSuccess: Processing tokens");
      const accessToken = searchParams.get("access_token");
      const refreshToken = searchParams.get("refresh_token");

      console.log("AccessToken present:", !!accessToken);

      if (accessToken) {
        try {
          // Store tokens in localStorage
          localStorage.setItem("access_token", accessToken);
          console.log("Stored access token");
          
          if (refreshToken) {
            localStorage.setItem("refresh_token", refreshToken);
            console.log("Stored refresh token");
          }

          // Clear OAuth state
          sessionStorage.removeItem("oauth_state");

          // Redirect to dashboard
          console.log("Redirecting to dashboard");
          setTimeout(() => router.push("/"), 500);
        } catch (error) {
          console.error("Error storing tokens:", error);
          router.push("/login?error=Failed+to+store+tokens");
        }
      } else {
        // No token, redirect to login
        console.error("No access token received");
        router.push("/login?error=No+access+token+received");
      }
    };

    processTokens();
  }, [mounted, searchParams, router]);

  if (!mounted) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gradient-to-br from-slate-900 to-slate-800">
        <div className="bg-white rounded-lg shadow-lg p-8 max-w-md mx-4">
          <div className="flex items-center justify-center mb-4">
            <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600"></div>
          </div>
          <p className="text-center text-gray-700 font-medium">
            Loading...
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-gradient-to-br from-slate-900 to-slate-800">
      <div className="bg-white rounded-lg shadow-lg p-8 max-w-md mx-4">
        <div className="flex items-center justify-center mb-4">
          <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600"></div>
        </div>
        <p className="text-center text-gray-700 font-medium">
          Authentication successful! Redirecting...
        </p>
      </div>
    </div>
  );
}

export default function AuthSuccessPage() {
  return (
    <Suspense fallback={
      <div className="min-h-screen flex items-center justify-center bg-gradient-to-br from-slate-900 to-slate-800">
        <div className="bg-white rounded-lg shadow-lg p-8 max-w-md mx-4">
          <div className="flex items-center justify-center mb-4">
            <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600"></div>
          </div>
          <p className="text-center text-gray-700 font-medium">Loading...</p>
        </div>
      </div>
    }>
      <AuthSuccessContent />
    </Suspense>
  );
}
