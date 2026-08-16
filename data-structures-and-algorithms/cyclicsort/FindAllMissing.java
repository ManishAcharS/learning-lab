package cyclicsort;
import java.util.ArrayList;
import java.util.List;

public class FindAllMissing {

    public static void main(String[] args) {

        int[] arr = {4, 3, 2, 7, 8, 2, 3, 1};

        System.out.println(find(arr));
    }

    // Finds all missing numbers
    static List<Integer> find(int[] arr) {

        CyclicSort.sort(arr);

        List<Integer> answer = new ArrayList<>();

        for (int i = 0; i < arr.length; i++) {

            if (arr[i] != i + 1) {
                answer.add(i + 1);
            }
        }

        return answer;
    }
}