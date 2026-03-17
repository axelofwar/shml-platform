import { render } from '@testing-library/react';
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from '@/components/ui/card';

describe('Card Component', () => {
  it('renders without crashing', () => {
    const { container } = render(
      <Card>
        <CardHeader>
          <CardTitle>Test Title</CardTitle>
          <CardDescription>Test Description</CardDescription>
        </CardHeader>
        <CardContent>Test Content</CardContent>
      </Card>
    );

    expect(container.querySelector('[class*="rounded-lg"]')).toBeInTheDocument();
  });

  it('applies custom className', () => {
    const { container } = render(
      <Card className="custom-class">
        <CardContent>Content</CardContent>
      </Card>
    );

    expect(container.querySelector('.custom-class')).toBeInTheDocument();
  });

  it('renders card title correctly', () => {
    const { getByText } = render(
      <Card>
        <CardHeader>
          <CardTitle>My Card Title</CardTitle>
        </CardHeader>
      </Card>
    );

    expect(getByText('My Card Title')).toBeInTheDocument();
  });
});
