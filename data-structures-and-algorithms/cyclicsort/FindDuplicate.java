package cyclicsort;
import utils.ArrayUtils;
public class FindDuplicate {

    public static void main(String[] args) {

        int[] arr = {1, 3, 4, 2, 2};

        System.out.println(find(arr));
    }

    // Finds one duplicate
    static int find(int[] arr) {

        int index = 0;

        while (index < arr.length) {

            if (arr[index] != index + 1) {

                int correct = arr[index] - 1;

                if (arr[index] != arr[correct]) {
                    ArrayUtils.swap(arr, index, correct);
                } else {
                    return arr[index];
                }

            } else {
                index++;
            }
        }

        return -1;
    }
}