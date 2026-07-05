package patterns;
public class Patterns {

    public static void main(String[] args) {

        pattern9(4);
    }

    // Square pattern
    static void pattern1(int n) {

        for (int row = 0; row < n; row++) {

            for (int col = 0; col < n; col++) {
                System.out.print(". ");
            }

            System.out.println();
        }
    }

    // Right triangle
    static void pattern2(int n) {

        for (int row = 0; row < n; row++) {

            for (int col = 0; col < row; col++) {
                System.out.print(". ");
            }

            System.out.println();
        }
    }

    // Inverted right triangle
    static void pattern3(int n) {

        for (int row = 0; row < n; row++) {

            for (int col = 0; col < n - row; col++) {
                System.out.print(". ");
            }

            System.out.println();
        }
    }

    // Number triangle
    static void pattern4(int n) {

        for (int row = 1; row <= n; row++) {

            for (int col = 1; col <= row; col++) {
                System.out.print(col + " ");
            }

            System.out.println();
        }
    }

    // Diamond half
    static void pattern5(int n) {

        for (int row = 0; row < 2 * n; row++) {

            int columns = row > n ? 2 * n - row : row;

            for (int col = 0; col < columns; col++) {
                System.out.print(". ");
            }

            System.out.println();
        }
    }

    // Centered diamond half
    static void pattern6(int n) {

        for (int row = 0; row < 2 * n; row++) {

            int columns = row > n ? 2 * n - row : row;
            int spaces = n - columns;

            for (int space = 0; space < spaces; space++) {
                System.out.print(" ");
            }

            for (int col = 0; col < columns; col++) {
                System.out.print(". ");
            }

            System.out.println();
        }
    }

    // Number pyramid
    static void pattern7(int n) {

        for (int row = 1; row <= n; row++) {

            int spaces = n - row;

            for (int space = 0; space < spaces; space++) {
                System.out.print("  ");
            }

            for (int col = row; col >= 1; col--) {
                System.out.print(col + " ");
            }

            for (int col = 2; col <= row; col++) {
                System.out.print(col + " ");
            }

            System.out.println();
        }
    }

    // Full number diamond
    static void pattern8(int n) {

        for (int row = 1; row <= 2 * n; row++) {

            int columns = row > n ? 2 * n - row : row;
            int spaces = n - columns;

            for (int space = 0; space < spaces; space++) {
                System.out.print("  ");
            }

            for (int col = columns; col >= 1; col--) {
                System.out.print(col + " ");
            }

            for (int col = 2; col <= columns; col++) {
                System.out.print(col + " ");
            }

            System.out.println();
        }
    }

    // Concentric square pattern
    static void pattern9(int n) {

        int size = 2 * n;

        for (int row = 1; row < size; row++) {

            for (int col = 1; col < size; col++) {

                int value = Math.min(
                        Math.min(row, col),
                        Math.min(size - row, size - col)
                );

                System.out.print(value + "  ");
            }

            System.out.println();
        }
    }
}