package recursion;
public class Fibonacci {

    public static void main(String[] args) {

        System.out.println(fibonacci(21));
    }

    // Finds nth Fibonacci number
    static int fibonacci(int n) {

        if (n < 2) {
            return n;
        }

        return fibonacci(n - 1) + fibonacci(n - 2);
    }
}