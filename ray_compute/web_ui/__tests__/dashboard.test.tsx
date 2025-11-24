import { render, screen, waitFor } from '@testing-library/react';
import { SessionProvider } from 'next-auth/react';
import DashboardPage from '@/app/page';

// Mock next-auth
jest.mock('next-auth/react');
jest.mock('next/navigation', () => ({
  useRouter: () => ({
    push: jest.fn(),
  }),
}));

describe('Dashboard Page', () => {
  const mockSession = {
    user: {
      name: 'Test User',
      email: 'test@example.com',
    },
    expires: '2025-12-31',
    accessToken: 'mock-token',
  };

  it('shows loading state initially', () => {
    (require('next-auth/react').useSession as jest.Mock).mockReturnValue({
      data: null,
      status: 'loading',
    });

    render(
      <SessionProvider session={null}>
        <DashboardPage />
      </SessionProvider>
    );

    expect(screen.queryByText('Dashboard')).not.toBeInTheDocument();
  });

  it('renders dashboard when authenticated', async () => {
    (require('next-auth/react').useSession as jest.Mock).mockReturnValue({
      data: mockSession,
      status: 'authenticated',
    });

    render(
      <SessionProvider session={mockSession}>
        <DashboardPage />
      </SessionProvider>
    );

    await waitFor(() => {
      expect(screen.getByText(/Ray Compute Platform/i)).toBeInTheDocument();
      expect(screen.getByText(/Test User/i)).toBeInTheDocument();
    });
  });

  it('displays stats cards', async () => {
    (require('next-auth/react').useSession as jest.Mock).mockReturnValue({
      data: mockSession,
      status: 'authenticated',
    });

    render(
      <SessionProvider session={mockSession}>
        <DashboardPage />
      </SessionProvider>
    );

    await waitFor(() => {
      expect(screen.getByText('Total Jobs')).toBeInTheDocument();
      expect(screen.getByText('Running Jobs')).toBeInTheDocument();
      expect(screen.getByText('GPU Hours')).toBeInTheDocument();
      expect(screen.getByText('Avg Duration')).toBeInTheDocument();
    });
  });

  it('has sign out button when authenticated', async () => {
    (require('next-auth/react').useSession as jest.Mock).mockReturnValue({
      data: mockSession,
      status: 'authenticated',
    });

    render(
      <SessionProvider session={mockSession}>
        <DashboardPage />
      </SessionProvider>
    );

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /sign out/i })).toBeInTheDocument();
    });
  });
});
