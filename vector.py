"""
vector.py - 2D Vector klasse voor positie en richting
"""

class Vector:
    def __init__(self, x, y):
        self.x = x
        self.y = y

    def __add__(self, other):
        return Vector(self.x + other.x, self.y + other.y)

    def __sub__(self, other):
        return Vector(self.x - other.x, self.y - other.y)

    def __mul__(self, other):
        try:
            return self.x * other.x + self.y * other.y  # Dot product
        except:
            return Vector(self.x * other, self.y * other)  # Scale

    def __truediv__(self, a):
        return Vector(self.x / a, self.y / a)

    def __len__(self):
        return int((self.x ** 2 + self.y ** 2) ** 0.5)

    def __str__(self):
        return f"({self.x}, {self.y})"

    def __iter__(self):
        return iter((self.x, self.y))