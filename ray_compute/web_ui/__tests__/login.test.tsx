import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { SessionProvider } from 'next-auth/react';
import { signIn } from 'next-auth/react';
import LoginPage from '@/app/login/page';

jest.mock('next-auth/react');
jest.mock('next/navigation');

describe('Login Page', () => {
  it('renders login button', () => {
    (require('next-auth/react').useSession as jest.Mock).mockReturnValue({
      data: null,
      status: 'unauthenticated',
    });

    render(
      <SessionProvider session={null}>
        <LoginPage />
      </SessionProvider>
    );

    expect(screen.getByText(/Sign in with Authentik/i)).toBeInTheDocument();
  });

  it('calls signIn when button clicked', async () => {
    const mockSignIn = jest.fn();
    (require('next-auth/react').signIn as jest.Mock) = mockSignIn;
    (require('next-auth/react').useSession as jest.Mock).mockReturnValue({
      data: null,
      status: 'unauthenticated',
    });

    render(
      <SessionProvider session={null}>
        <LoginPage />
      </SessionProvider>
    );

    const button = screen.getByText(/Sign in with Authentik/i);
    fireEvent.click(button);

    await waitFor(() => {
      expect(mockSignIn).toHaveBeenCalledWith('authentik', { callbackUrl: '/' });
    });
  });

  it('redirects if already authenticated', () => {
    const mockPush = jest.fn();
    (require('next/navigation').useRouter as jest.Mock).mockReturnValue({
      push: mockPush,
    });
    (require('next-auth/react').useSession as jest.Mock).mockReturnValue({
      data: { user: { name: 'Test' } },
      status: 'authenticated',
    });

    render(
      <SessionProvider session={{ user: { name: 'Test' }, expires: '2025-12-31' }}>
        <LoginPage />
      </SessionProvider>
    );

    expect(mockPush).toHaveBeenCalledWith('/');
  });
});
