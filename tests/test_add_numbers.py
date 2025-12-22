import pytest


def add_numbers(a, b):
    """
    Add two numbers together.

    Parameters
    ----------
    a : int or float
        The first number.
    b : int or float
        The second number.

    Returns
    -------
    int or float
        The sum of ``a`` and ``b``.
    """
    return a + b


def test_add_positive_integers():
    """Test addition of two positive integers."""
    assert add_numbers(1, 2) == 3
    assert add_numbers(10, 20) == 30


def test_add_negative_integers():
    """Test addition of two negative integers."""
    assert add_numbers(-1, -2) == -3
    assert add_numbers(-10, -20) == -30


def test_add_mixed_signs():
    """Test addition where one operand is positive and the other is negative."""
    assert add_numbers(5, -3) == 2
    assert add_numbers(-5, 3) == -2


def test_add_zero():
    """Test addition with zero."""
    assert add_numbers(0, 0) == 0
    assert add_numbers(0, 5) == 5
    assert add_numbers(7, 0) == 7


def test_add_floats():
    """Test addition of floating‑point numbers."""
    assert add_numbers(1.5, 2.3) == pytest.approx(3.8)
    assert add_numbers(-0.5, 0.5) == pytest.approx(0.0)


def test_add_large_numbers():
    """Test addition of large integers."""
    large = 10**12
    assert add_numbers(large, large) == 2 * large
    assert add_numbers(large, -large) == 0


def test_add_custom_objects_with_add_method():
    """
    Test addition when operands implement the ``__add__`` method.

    This demonstrates that ``add_numbers`` works with any objects that
    define a compatible addition operation.
    """

    class Counter:
        """Simple integer wrapper with addition support."""

        def __init__(self, value):
            self.value = value

        def __add__(self, other):
            if isinstance(other, Counter):
                return Counter(self.value + other.value)
            return Counter(self.value + other)

        def __eq__(self, other):
            if isinstance(other, Counter):
                return self.value == other.value
            return self.value == other

        def __repr__(self):
            return f"Counter({self.value})"

    a = Counter(10)
    b = Counter(5)
    result = add_numbers(a, b)
    assert result == Counter(15)
    assert repr(result) == "Counter(15)"


def test_add_invalid_types_raises_type_error():
    """
    Verify that adding incompatible types raises a ``TypeError``.
    """
    with pytest.raises(TypeError):
        add_numbers(1, "string")
    with pytest.raises(TypeError):
        add_numbers(None, 5)
    with pytest.raises(TypeError):
        add_numbers([], {})
