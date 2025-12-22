import unittest


def add_numbers(a, b):
    """
    Add two numbers.

    Args:
        a (int or float): First operand.
        b (int or float): Second operand.

    Returns:
        int or float: The sum of ``a`` and ``b``.
    """
    return a + b


def multiply_numbers(a, b):
    """
    Multiply two numbers.

    Args:
        a (int or float): First operand.
        b (int or float): Second operand.

    Returns:
        int or float: The product of ``a`` and ``b``.
    """
    return a * b


class TestCalculator(unittest.TestCase):
    """Test suite for the calculator functions."""

    def test_add_positive_numbers(self):
        """Adding two positive integers."""
        self.assertEqual(add_numbers(2, 3), 5)

    def test_add_negative_numbers(self):
        """Adding two negative integers."""
        self.assertEqual(add_numbers(-1, -4), -5)

    def test_add_mixed_signs(self):
        """Adding a positive and a negative integer."""
        self.assertEqual(add_numbers(7, -3), 4)

    def test_add_floats(self):
        """Adding floating‑point numbers."""
        self.assertAlmostEqual(add_numbers(2.5, 3.1), 5.6)

    def test_multiply_positive_numbers(self):
        """Multiplying two positive integers."""
        self.assertEqual(multiply_numbers(4, 5), 20)

    def test_multiply_negative_numbers(self):
        """Multiplying two negative integers."""
        self.assertEqual(multiply_numbers(-2, -3), 6)

    def test_multiply_mixed_signs(self):
        """Multiplying a positive and a negative integer."""
        self.assertEqual(multiply_numbers(-4, 2), -8)

    def test_multiply_floats(self):
        """Multiplying floating‑point numbers."""
        self.assertAlmostEqual(multiply_numbers(1.5, 2.0), 3.0)


if __name__ == "__main__":
    unittest.main()
