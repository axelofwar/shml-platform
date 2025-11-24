import '@testing-library/jest-dom';

// Mock next-auth
jest.mock('next-auth/react', () => ({
  useSession: jest.fn(() => ({
    data: null,
    status: 'loading',
  })),
  signIn: jest.fn(),
  signOut: jest.fn(),
  SessionProvider: ({ children }) => children,
}));

// Mock next/navigation
jest.mock('next/navigation', () => ({
  useRouter: jest.fn(() => ({
    push: jest.fn(),
    replace: jest.fn(),
    prefetch: jest.fn(),
  })),
  usePathname: jest.fn(),
}));

// Mock lucide-react icons
jest.mock('lucide-react', () => ({
  Activity: () => <svg data-testid="activity-icon" />,
  Cpu: () => <svg data-testid="cpu-icon" />,
  Zap: () => <svg data-testid="zap-icon" />,
  Clock: () => <svg data-testid="clock-icon" />,
  LogOut: () => <svg data-testid="logout-icon" />,
  ArrowUpRight: () => <svg data-testid="arrow-icon" />,
}));

// Suppress console errors in tests
global.console = {
  ...console,
  error: jest.fn(),
  warn: jest.fn(),
};
