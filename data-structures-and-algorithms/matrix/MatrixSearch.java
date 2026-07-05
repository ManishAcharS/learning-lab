package matrix;
public class MatrixSearch {

    public static void main(String[] args) {

        int[][] matrix = {
                {4, 5, 6, 7},
                {5, 9, 11, 14},
                {6, 11, 18, 21},
                {8, 12, 21, 27}
        };

        System.out.println(search(matrix, 21));
    }

    // Searches in a sorted matrix
    static int search(int[][] matrix, int target) {

        int row = 0;
        int col = matrix[0].length - 1;

        while (row < matrix.length && col >= 0) {

            if (matrix[row][col] == target) {
                return matrix[row][col];
            }

            if (target < matrix[row][col]) {
                col--;
            } else {
                row++;
            }
        }

        return -1;
    }
}