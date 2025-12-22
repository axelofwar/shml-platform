"""
calculator.py

This module provides simple arithmetic operations for educational purposes.
It includes functions for addition and multiplication of numbers.

Functions
---------
add_numbers(a, b)
    Return the sum of two numbers.
multiply_numbers(a, b)
    Return the product of two numbers.
"""

# ----------------------------------------------------------------------
# Imports
# ----------------------------------------------------------------------
# No external dependencies are required for this module.


# ----------------------------------------------------------------------
# Functions
# ----------------------------------------------------------------------
def add_numbers(a, b):
    """
    Add two numbers.

    Parameters
    ----------
    a : int or float
        The first operand.
    b : int or float
        The second operand.

    Returns
    -------
    int or float
        The sum of ``a`` and ``b``.
    """
    # The addition operator works with both integers and floating‑point numbers.
    return a + b


def multiply_numbers(a, b):
    """
    Multiply two numbers.

    Parameters
    ----------
    a : int or float
        The first operand.
    b : int or float
        The second operand.

    Returns
    -------
    int or float
        The product of ``a`` and ``b``.
    """
    # The multiplication operator works with both integers and floating‑point numbers.
    return a * b


# ----------------------------------------------------------------------
# Simple self‑test (executed only when run as a script)
# ----------------------------------------------------------------------
if __name__ == "__main__":
    # Example usage of the functions
    x, y = 5, 3

    # Addition
    sum_result = add_numbers(x, y)
    print(f"{x} + {y} = {sum_result}")

    # Multiplication
    product_result = multiply_numbers(x, y)
    print(f"{x} * {y} = {product_result}")

    # Demonstrate handling of floats
    a, b = 2.5, 4
    print(f"{a} + {b} = {add_numbers(a, b)}")
    print(f"{a} * {b} = {multiply_numbers(a, b)}")
