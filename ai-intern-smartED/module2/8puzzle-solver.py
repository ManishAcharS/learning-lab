from collections import deque

goal_state = [[1, 2, 3],
              [4, 5, 6],
              [7, 8, 0]]

actions = [(-1, 0), (1, 0), (0, -1), (0, 1)] # up, down, left, right


def find_blank(state):
    for i in range(3):
        for j in range(3):
            if state[i][j] == 0:
                return i, j
    return None


def is_valid(x, y):
    return 0 <= x < 3 and 0 <= y < 3


def move(state, dx, dy):
    x, y = find_blank(state)

    new_x = x + dx
    new_y = y + dy

    if not is_valid(new_x, new_y):
        return None

    new_state = [row[:] for row in state]

    new_state[x][y], new_state[new_x][new_y] = \
        new_state[new_x][new_y], new_state[x][y]

    return new_state


def is_goal(state):
    return state == goal_state


def state_to_tuple(state):
    return tuple(tuple(row) for row in state)


def bfs(initial_state):
    visited = set()

    queue = deque([(initial_state, [])])

    visited.add(state_to_tuple(initial_state))

    while queue:

        current, path = queue.popleft()

        if is_goal(current):
            return path + [current]

        for dx, dy in actions:

            next_state = move(current, dx, dy)

            if next_state is not None:

                state_tuple = state_to_tuple(next_state)

                if state_tuple not in visited:
                    visited.add(state_tuple)

                    queue.append(
                        (next_state, path + [current])
                    )

    return None


initial_state = [[1,7,3],
                 [4,0,6],
                 [2,8,5]]

solution_path = bfs(initial_state)

if solution_path:

    print("Solution found in:",
          len(solution_path) - 1,
          "moves.")

    for step_number, step in enumerate(solution_path):

        print("Step", step_number)

        for row in step:
            print(row)

        print("------------")

else:

    print("No solution found.")
