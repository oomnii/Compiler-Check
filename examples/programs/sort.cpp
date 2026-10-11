#include <algorithm>
#include <iostream>
#include <vector>

int main() {
    int n;
    if (!(std::cin >> n) || n < 0) {
        return 1;
    }
    std::vector<int> v(static_cast<std::size_t>(n));
    for (int i = 0; i < n; ++i) {
        if (!(std::cin >> v[static_cast<std::size_t>(i)])) {
            return 1;
        }
    }
    std::sort(v.begin(), v.end());
    for (int i = 0; i < n; ++i) {
        if (i) {
            std::cout << ' ';
        }
        std::cout << v[static_cast<std::size_t>(i)];
    }
    std::cout << '\n';
    return 0;
}
